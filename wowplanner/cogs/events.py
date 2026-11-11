"""Sorties : création, annulation, inscriptions par boutons (avec choix du personnage)."""
from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import Counter, defaultdict
from datetime import datetime
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..db import Character, Event
from ..embeds import build_event_embed
from ..gamedata import can_play, class_label, race_label, roles_for
from ..roles import LABELS, ROLES, RoleEmojis, resolve_composition
from ..timeparse import parse_when

if TYPE_CHECKING:
    from ..bot import WowPlannerBot

log = logging.getLogger(__name__)

# Les sorties commencées depuis plus longtemps ne sont plus resynchronisées au démarrage.
RESYNC_GRACE_SECONDS = 12 * 3600

REQUIRED_PERMS = {
    "view_channel": "Voir le salon",
    "send_messages": "Envoyer des messages",
    "embed_links": "Intégrer des liens",
    "read_message_history": "Voir les anciens messages",
}

# custom_id fixes : les boutons continuent de marcher après un redémarrage du bot.
SIGNUP_ID = "wowplanner:signup:"
LEAVE_ID = "wowplanner:leave"

Messageable = discord.TextChannel | discord.Thread | discord.VoiceChannel


def describe_character(c: Character) -> str:
    return f"{class_label(c.wow_class)} {race_label(c.race)}"


class SignupView(discord.ui.View):
    """Boutons sous un message de sortie.

    Sans `caps`, c'est la vue générique enregistrée au démarrage : elle répond aux clics sur
    n'importe quel message de sortie. Avec `caps`, elle sert à afficher l'état d'une sortie
    (rôles complets en gris). Un rôle complet reste cliquable : le joueur déjà inscrit dans
    ce rôle doit pouvoir changer de perso, les autres reçoivent un refus.
    """

    def __init__(
        self,
        cog: EventsCog,
        emojis: RoleEmojis,
        caps: dict[str, int] | None = None,
        counts: Counter[str] | None = None,
    ):
        super().__init__(timeout=None)
        self.cog = cog
        for role in ROLES:
            if caps is not None and caps[role] <= 0:
                continue
            full = caps is not None and counts is not None and counts[role] >= caps[role]
            button = discord.ui.Button(
                label=f"{LABELS[role]} · complet" if full else LABELS[role],
                emoji=emojis[role],
                style=discord.ButtonStyle.secondary if full else discord.ButtonStyle.primary,
                custom_id=SIGNUP_ID + role,
            )
            button.callback = self._signup_callback(role)
            self.add_item(button)
        leave = discord.ui.Button(label="Se désinscrire", style=discord.ButtonStyle.danger, custom_id=LEAVE_ID)
        leave.callback = self._leave
        self.add_item(leave)

    def _signup_callback(self, role: str):
        async def callback(interaction: discord.Interaction) -> None:
            await self.cog.handle_signup(interaction, role)

        return callback

    async def _leave(self, interaction: discord.Interaction) -> None:
        await self.cog.handle_leave(interaction)


class CharacterPickView(discord.ui.View):
    """Menu privé (éphémère) pour choisir le perso quand plusieurs peuvent tenir le rôle."""

    def __init__(self, cog: EventsCog, message_id: int, role: str, characters: list[Character], default_id: int | None):
        super().__init__(timeout=180)
        self.cog = cog
        self.message_id = message_id
        self.role = role
        self.characters = {c.id: c for c in characters}
        select = discord.ui.Select(
            placeholder="Choisis ton perso",
            options=[
                discord.SelectOption(
                    label=c.name[:100],
                    description=(describe_character(c) + (" · ⭐ rôle préféré" if c.preferred_role == role else ""))[:100],
                    value=str(c.id),
                    default=c.id == default_id,
                )
                for c in characters[:25]
            ],
        )
        select.callback = self._picked
        self.add_item(select)
        self.select = select

    async def _picked(self, interaction: discord.Interaction) -> None:
        character = self.characters[int(self.select.values[0])]
        _, text = await self.cog.register(self.message_id, interaction.user, self.role, character)
        await interaction.response.edit_message(content=text, view=None)
        self.stop()
        await self.cog.refresh_event(self.message_id)


class ConfirmCancelView(discord.ui.View):
    """Confirmation avant d'annuler une sortie (les inscrits sont prévenus, c'est irréversible)."""

    def __init__(self, cog: EventsCog, message_id: int):
        super().__init__(timeout=60)
        self.cog = cog
        self.message_id = message_id

    @discord.ui.button(label="Oui, annuler la sortie", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        text = await self.cog.do_cancel(self.message_id)
        await interaction.response.edit_message(content=text, view=None)

    @discord.ui.button(label="Non, garder", style=discord.ButtonStyle.secondary)
    async def abort(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(content="La sortie est maintenue.", view=None)


class EventsCog(commands.Cog):
    """Sorties : logique des commandes (déclarées dans cogs/commands.py), boutons d'inscription, resynchronisation."""

    def __init__(self, bot: WowPlannerBot):
        self.bot = bot
        self.db = bot.db
        self.emojis = bot.role_emojis
        self.instances = bot.instances
        self._locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._resynced = False

    async def cog_load(self) -> None:
        self.bot.add_view(SignupView(self, self.emojis))

    def _view_for(self, ev: Event, signups) -> SignupView | None:
        if ev.cancelled:
            return None
        return SignupView(self, self.emojis, ev.caps, Counter(s.role for s in signups))

    # ================================================================== commandes

    async def create(
        self,
        interaction: discord.Interaction,
        instance: str,
        date: str,
        heure: str,
        joueurs: int | None,
        tanks: int | None,
        heals: int | None,
        dps: int | None,
        description: str | None,
    ) -> None:
        channel = interaction.channel
        if interaction.guild is None or not isinstance(channel, Messageable):
            await interaction.response.send_message("Commande utilisable uniquement dans un salon de serveur.", ephemeral=True)
            return

        allowed = self.bot.config.event_channel_ids
        if allowed and channel.id not in allowed:
            where = ", ".join(f"<#{cid}>" for cid in allowed)
            await interaction.response.send_message(f"Les sorties se créent dans {where}.", ephemeral=True)
            return

        missing = self._missing_perms(channel)
        if missing:
            await interaction.response.send_message(
                "Il me manque des permissions dans ce salon :\n" + "\n".join(f"• {m}" for m in missing),
                ephemeral=True,
            )
            return

        inst = self.instances.get(instance)
        try:
            caps = resolve_composition(joueurs, inst.size if inst else None, tanks, heals, dps)
            starts = parse_when(date, heure, self.bot.config.timezone)
        except ValueError as exc:
            await interaction.response.send_message(f"⚠️ {exc}", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        ev = Event(
            message_id=0,
            guild_id=interaction.guild.id,
            channel_id=channel.id,
            creator_id=interaction.user.id,
            instance=inst.name if inst else instance.strip(),
            kind=inst.kind if inst else "custom",
            levels=inst.levels if inst else None,
            starts_at=int(starts.timestamp()),
            caps=caps,
            description=description,
        )
        try:
            message = await channel.send(embed=build_event_embed(ev, [], self.emojis), view=self._view_for(ev, []))
            ev.message_id = message.id
            self.db.create_event(ev)
        except discord.HTTPException as exc:
            log.exception("Création de sortie impossible")
            await interaction.followup.send(f"⚠️ Impossible de créer la sortie : {exc}", ephemeral=True)
            return

        warn = ""
        if inst and sum(caps.values()) > inst.size:
            warn = f"\n⚠️ Attention : {inst.name} est limité à {inst.size} joueurs."
        await interaction.followup.send(f"✅ Sortie créée : {message.jump_url}{warn}", ephemeral=True)

    def instance_choices(self, current: str) -> list[app_commands.Choice[str]]:
        return [
            app_commands.Choice(name=i.choice_label(), value=i.name[:100])
            for i in self.instances.search(current)
        ]

    async def cancel(self, interaction: discord.Interaction, sortie: str) -> None:
        """Demande confirmation ; l'annulation elle-même est dans do_cancel."""
        ev = await self._resolve_managed_event(interaction, sortie)
        if ev is None:
            return
        count = len(self.db.get_signups(ev.message_id))
        await interaction.response.send_message(
            f"Annuler **{ev.instance}** du <t:{ev.starts_at}:F> ? "
            f"Les {count} inscrit(s) seront prévenus." if count else
            f"Annuler **{ev.instance}** du <t:{ev.starts_at}:F> ?",
            view=ConfirmCancelView(self, ev.message_id),
            ephemeral=True,
        )

    async def do_cancel(self, message_id: int) -> str:
        async with self._locks[message_id]:
            ev = self.db.get_event(message_id)
            if ev is None or ev.cancelled:
                return "Cette sortie n'existe plus ou est déjà annulée."
            self.db.set_cancelled(ev.message_id)
            ev.cancelled = True
            signups = self.db.get_signups(ev.message_id)
            await self._refresh(ev)  # retire les boutons
            if signups:
                try:
                    channel = await self._channel(ev.channel_id)
                    mentions = " ".join(f"<@{s.user_id}>" for s in signups)
                    await channel.get_partial_message(ev.message_id).reply(
                        f"❌ La sortie **{ev.instance}** du <t:{ev.starts_at}:F> est annulée. {mentions}",
                        allowed_mentions=discord.AllowedMentions(users=True),
                    )
                except discord.HTTPException as exc:
                    log.warning("Annulation de %s : inscrits non prévenus (%s)", ev.message_id, exc)
        return f"❌ Sortie **{ev.instance}** du <t:{ev.starts_at}:F> annulée."

    async def kick(self, interaction: discord.Interaction, sortie: str, joueur: str) -> None:
        """Désinscrit un joueur d'UNE sortie précise : `joueur` doit être un inscrit de `sortie`."""
        ev = await self._resolve_managed_event(interaction, sortie)
        if ev is None:
            return
        ids = re.findall(r"\d{15,20}", joueur)
        user_id = int(ids[-1]) if ids else 0
        await interaction.response.defer(ephemeral=True)
        async with self._locks[ev.message_id]:
            signup = next((s for s in self.db.get_signups(ev.message_id) if s.user_id == user_id), None)
            if signup is None:
                await interaction.followup.send(
                    f"Ce joueur n'est pas inscrit à **{ev.instance}** du <t:{ev.starts_at}:F>. "
                    "Choisis-le dans la liste proposée (elle ne montre que les inscrits de cette sortie).",
                    ephemeral=True,
                )
                return
            self.db.delete_signup(ev.message_id, user_id)
            await self._refresh(ev)
        await interaction.followup.send(
            f"<@{user_id}> a été désinscrit de **{ev.instance}** du <t:{ev.starts_at}:F> "
            "(ses autres sorties ne changent pas).",
            ephemeral=True,
        )

    async def list_events(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        events = self.db.upcoming_events(interaction.guild.id, int(time.time()) - 3600)[:20]
        if not events:
            await interaction.response.send_message("Aucune sortie prévue.", ephemeral=True)
            return
        lines = []
        for ev in events:
            count = len(self.db.get_signups(ev.message_id))
            url = f"https://discord.com/channels/{ev.guild_id}/{ev.channel_id}/{ev.message_id}"
            lines.append(f"<t:{ev.starts_at}:f> — **{ev.instance}** ({count}/{ev.size}) · [voir]({url})")
        embed = discord.Embed(title="📅 Prochaines sorties", description="\n".join(lines), color=0x3498DB)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    def event_choices(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        if interaction.guild is None:
            return []
        q = current.lower()
        tz = self.bot.config.timezone
        choices = []
        for ev in self.db.upcoming_events(interaction.guild.id, int(time.time()) - 6 * 3600):
            when = datetime.fromtimestamp(ev.starts_at, tz).strftime("%d/%m %H:%M")
            label = f"{when} · {ev.instance}"
            if q in label.lower():
                choices.append(app_commands.Choice(name=label[:100], value=str(ev.message_id)))
        return choices[:25]

    def signup_choices(self, sortie: str | None, current: str) -> list[app_commands.Choice[str]]:
        """Inscrits de la sortie déjà choisie dans le champ `sortie` (et seulement d'elle)."""
        ids = re.findall(r"\d{15,20}", sortie or "")
        if not ids:
            return []
        q = current.lower()
        choices = []
        for s in self.db.get_signups(int(ids[-1])):
            who = s.display_name or str(s.user_id)
            label = f"{who} — {LABELS[s.role]}" + (f" ({s.character_name})" if s.character_name else "")
            if q in label.lower():
                choices.append(app_commands.Choice(name=label[:100], value=str(s.user_id)))
        return choices[:25]

    # ============================================================ boutons

    async def handle_signup(self, interaction: discord.Interaction, role: str) -> None:
        message_id = interaction.message.id if interaction.message else 0
        ev = self.db.get_event(message_id)
        if ev is None or ev.cancelled or ev.caps[role] <= 0:
            await interaction.response.send_message("Cette sortie n'est plus ouverte à ce rôle.", ephemeral=True)
            return

        signups = self.db.get_signups(message_id)
        current = next((s for s in signups if s.user_id == interaction.user.id), None)
        if sum(1 for s in signups if s.role == role and s.user_id != interaction.user.id) >= ev.caps[role]:
            await interaction.response.send_message(
                f"Le rôle **{LABELS[role]}** est complet pour **{ev.instance}**.", ephemeral=True
            )
            return

        self.db.touch_member(ev.guild_id, interaction.user.id)
        characters = self.db.get_characters(interaction.user.id)
        # Les persos dont c'est le rôle préféré passent en premier.
        capable = sorted(
            (c for c in characters if can_play(c.wow_class, role)), key=lambda c: c.preferred_role != role
        )

        if characters and not capable:
            mine = "\n".join(
                f"• **{c.name}** ({describe_character(c)}) : {', '.join(LABELS[r] for r in roles_for(c.wow_class))}"
                for c in characters
            )
            await interaction.response.send_message(
                f"Aucun de tes persos ne peut jouer **{LABELS[role]}** :\n{mine}\n"
                "Ajoute un perso avec `/ajouter perso` ou choisis un autre rôle.",
                ephemeral=True,
            )
            return

        if len(capable) > 1:
            if current and current.role == role and current.character_id:
                default_id = current.character_id
            else:
                default_id = capable[0].id if capable[0].preferred_role == role else None
            await interaction.response.send_message(
                f"Quel perso pour **{LABELS[role]}** sur **{ev.instance}** ?",
                view=CharacterPickView(self, message_id, role, capable, default_id),
                ephemeral=True,
            )
            return

        changed, text = await self.register(message_id, interaction.user, role, capable[0] if capable else None)
        await interaction.response.send_message(text, ephemeral=True)
        if changed:
            await self.refresh_event(message_id)

    async def register(
        self, message_id: int, user: discord.abc.User, role: str, character: Character | None
    ) -> tuple[bool, str]:
        """Inscrit le joueur. Renvoie (inscription modifiée ?, message pour le joueur)."""
        async with self._locks[message_id]:
            ev = self.db.get_event(message_id)
            if ev is None or ev.cancelled:
                return False, "Cette sortie n'est plus ouverte."
            if character is not None and self.db.get_character(character.id) is None:
                return False, f"Le perso **{character.name}** n'existe plus."

            signups = self.db.get_signups(message_id)
            current = next((s for s in signups if s.user_id == user.id), None)
            taken = sum(1 for s in signups if s.role == role and s.user_id != user.id)
            if taken >= ev.caps[role]:
                return False, f"Le rôle **{LABELS[role]}** est complet pour **{ev.instance}**."

            char_id = character.id if character else None
            if current and current.role == role and current.character_id == char_id:
                return False, f"Tu es déjà inscrit en **{LABELS[role]}**."

            self.db.upsert_signup(message_id, user.id, role, getattr(user, "display_name", None), char_id)

        who = f" avec **{character.name}** ({describe_character(character)})" if character else ""
        verb = "Tu passes" if current and current.role != role else "Inscrit"
        text = f"✅ {verb} en **{LABELS[role]}**{who} pour **{ev.instance}** (<t:{ev.starts_at}:F>)."
        if character is None:
            text += "\n💡 Déclare tes persos avec `/ajouter perso` pour qu'ils s'affichent dans les sorties."
        return True, text

    async def handle_leave(self, interaction: discord.Interaction) -> None:
        message_id = interaction.message.id if interaction.message else 0
        async with self._locks[message_id]:
            ev = self.db.get_event(message_id)
            signed = ev is not None and any(s.user_id == interaction.user.id for s in self.db.get_signups(message_id))
            if signed:
                self.db.delete_signup(message_id, interaction.user.id)
        if not signed:
            await interaction.response.send_message("Tu n'es pas inscrit à cette sortie.", ephemeral=True)
            return
        await interaction.response.send_message(f"Tu es désinscrit de **{ev.instance}**.", ephemeral=True)
        await self.refresh_event(message_id)

    # ============================================================ événements

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Filet de sécurité : dans les salons de sorties, seuls le bot et les modérateurs écrivent."""
        allowed = self.bot.config.event_channel_ids
        if not allowed or message.guild is None or message.channel.id not in allowed:
            return
        if message.author.id == self.bot.user.id or message.type not in (
            discord.MessageType.default,
            discord.MessageType.reply,
        ):
            return
        author = message.author
        if isinstance(author, discord.Member) and message.channel.permissions_for(author).manage_messages:
            return
        try:
            await message.delete()
        except discord.HTTPException as exc:
            log.warning("Impossible de supprimer le message %s : %s", message.id, exc)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent) -> None:
        ev = self.db.get_event(payload.message_id)
        if ev is not None:
            schedule = self.bot.get_cog("ScheduleCog")
            if schedule is not None and ev.voice_channel_id:
                await schedule.delete_voice_if_empty(ev)
            self.db.delete_event(payload.message_id)
            log.info("Sortie %s supprimée avec son message", payload.message_id)

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        # Remet les boutons à jour, et convertit les sorties créées avec l'ancien système de réactions.
        if self._resynced:
            return
        self._resynced = True
        events = self.db.active_events(int(time.time()) - RESYNC_GRACE_SECONDS)
        log.info("Resynchronisation de %d sortie(s) active(s)…", len(events))
        for ev in events:
            async with self._locks[ev.message_id]:
                await self._resync(ev)

    # ============================================================== interne

    async def refresh_event(self, message_id: int) -> None:
        """Recharge la sortie depuis la base et met à jour son message."""
        async with self._locks[message_id]:
            ev = self.db.get_event(message_id)
            if ev is not None:
                await self._refresh(ev)

    async def _resync(self, ev: Event) -> None:
        try:
            channel = await self._channel(ev.channel_id)
            message = await channel.fetch_message(ev.message_id)
        except discord.NotFound:
            self.db.delete_event(ev.message_id)
            return
        except discord.HTTPException as exc:
            log.warning("Resync %s impossible : %s", ev.message_id, exc)
            return
        if message.reactions:
            # Sortie de l'ancienne version (inscription par réaction) : les inscrits sont déjà en base.
            try:
                await message.clear_reactions()
            except discord.HTTPException as exc:
                log.warning("Réactions de %s non retirées : %s", ev.message_id, exc)
        await self._refresh(ev)

    async def _refresh(self, ev: Event) -> None:
        """Met à jour l'embed et les boutons (retirés si la sortie est annulée)."""
        try:
            channel = await self._channel(ev.channel_id)
            signups = self.db.get_signups(ev.message_id)
            await channel.get_partial_message(ev.message_id).edit(
                embed=build_event_embed(ev, signups, self.emojis), view=self._view_for(ev, signups)
            )
        except discord.NotFound:
            self.db.delete_event(ev.message_id)
        except discord.HTTPException as exc:
            log.warning("Mise à jour de la sortie %s impossible : %s", ev.message_id, exc)

    async def _channel(self, channel_id: int):
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            channel = await self.bot.fetch_channel(channel_id)
        return channel

    def _missing_perms(self, channel: Messageable) -> list[str]:
        perms = channel.permissions_for(channel.guild.me)
        return [label for name, label in REQUIRED_PERMS.items() if not getattr(perms, name)]

    async def _resolve_managed_event(self, interaction: discord.Interaction, value: str) -> Event | None:
        """Retrouve une sortie (ID ou lien de message) et vérifie que l'utilisateur peut la gérer."""
        ids = re.findall(r"\d{15,20}", value)
        ev = self.db.get_event(int(ids[-1])) if ids else None
        if ev is None or interaction.guild is None or ev.guild_id != interaction.guild.id:
            await interaction.response.send_message("Sortie introuvable.", ephemeral=True)
            return None
        if ev.cancelled:
            await interaction.response.send_message("Cette sortie est déjà annulée.", ephemeral=True)
            return None
        perms = interaction.permissions
        if interaction.user.id != ev.creator_id and not (perms.manage_messages or perms.manage_events):
            await interaction.response.send_message(
                "Seul l'organisateur ou un modérateur peut faire ça.", ephemeral=True
            )
            return None
        return ev


async def setup(bot: WowPlannerBot) -> None:
    await bot.add_cog(EventsCog(bot))
