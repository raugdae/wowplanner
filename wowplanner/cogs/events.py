"""Commandes /event et gestion des inscriptions par réaction."""
from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import Counter, defaultdict
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import discord
from discord import app_commands
from discord.ext import commands

from ..db import Event
from ..embeds import build_event_embed
from ..roles import LABELS, ROLES, AnyEmoji, resolve_composition
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
    "add_reactions": "Ajouter des réactions",
    "manage_messages": "Gérer les messages (pour retirer les réactions refusées)",
    "read_message_history": "Voir les anciens messages",
}

Messageable = discord.TextChannel | discord.Thread | discord.VoiceChannel


class EventsCog(commands.Cog):
    event = app_commands.Group(
        name="event", description="Organiser une sortie donjon / raid", guild_only=True
    )

    def __init__(self, bot: WowPlannerBot):
        self.bot = bot
        self.db = bot.db
        self.emojis = bot.role_emojis
        self.instances = bot.instances
        self._locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._resynced = False

    # ================================================================== commandes

    @event.command(name="creer", description="Créer une sortie donjon/raid avec inscription par réaction")
    @app_commands.describe(
        instance="Donjon ou raid (tape pour chercher, ou saisis un nom libre)",
        date="JJ/MM/AAAA, JJ/MM, « aujourd'hui » ou « demain »",
        heure="Heure de rendez-vous : 21:00, 21h30, 21h…",
        joueurs="Nombre total de joueurs (par défaut : taille de l'instance)",
        tanks="Nombre de places Tank",
        heals="Nombre de places Heal",
        dps="Nombre de places DPS",
        description="Infos complémentaires (stuff requis, point de RDV…)",
    )
    async def create(
        self,
        interaction: discord.Interaction,
        instance: app_commands.Range[str, 1, 100],
        date: str,
        heure: str,
        joueurs: Optional[app_commands.Range[int, 1, 40]] = None,
        tanks: Optional[app_commands.Range[int, 0, 40]] = None,
        heals: Optional[app_commands.Range[int, 0, 40]] = None,
        dps: Optional[app_commands.Range[int, 0, 40]] = None,
        description: Optional[app_commands.Range[str, 1, 500]] = None,
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
            message = await channel.send(embed=build_event_embed(ev, [], self.emojis))
            ev.message_id = message.id
            self.db.create_event(ev)
            async with self._locks[message.id]:
                for role in ROLES:
                    if caps[role] > 0:
                        await message.add_reaction(self.emojis[role])
        except discord.HTTPException as exc:
            log.exception("Création de sortie impossible")
            await interaction.followup.send(f"⚠️ Impossible de créer la sortie : {exc}", ephemeral=True)
            return

        warn = ""
        if inst and sum(caps.values()) > inst.size:
            warn = f"\n⚠️ Attention : {inst.name} est limité à {inst.size} joueurs."
        await interaction.followup.send(f"✅ Sortie créée : {message.jump_url}{warn}", ephemeral=True)

    @create.autocomplete("instance")
    async def _instance_autocomplete(self, interaction: discord.Interaction, current: str):
        return [
            app_commands.Choice(name=i.choice_label(), value=i.name[:100])
            for i in self.instances.search(current)
        ]

    @event.command(name="annuler", description="Annuler une sortie (organisateur ou modérateur)")
    @app_commands.describe(sortie="La sortie à annuler")
    async def cancel(self, interaction: discord.Interaction, sortie: str) -> None:
        ev = await self._resolve_managed_event(interaction, sortie)
        if ev is None:
            return
        await interaction.response.defer(ephemeral=True)
        async with self._locks[ev.message_id]:
            self.db.set_cancelled(ev.message_id)
            ev.cancelled = True
            signups = self.db.get_signups(ev.message_id)
            try:
                channel = await self._channel(ev.channel_id)
                message = await channel.fetch_message(ev.message_id)
                await message.edit(embed=build_event_embed(ev, signups, self.emojis))
                await message.clear_reactions()
                if signups:
                    mentions = " ".join(f"<@{s.user_id}>" for s in signups)
                    await message.reply(
                        f"❌ La sortie **{ev.instance}** du <t:{ev.starts_at}:F> est annulée. {mentions}",
                        allowed_mentions=discord.AllowedMentions(users=True),
                    )
            except discord.HTTPException as exc:
                log.warning("Annulation de %s : message non mis à jour (%s)", ev.message_id, exc)
        await interaction.followup.send("Sortie annulée.", ephemeral=True)

    @event.command(name="retirer", description="Désinscrire un joueur d'une sortie (organisateur ou modérateur)")
    @app_commands.describe(sortie="La sortie concernée", joueur="Le joueur à retirer")
    async def kick(self, interaction: discord.Interaction, sortie: str, joueur: discord.User) -> None:
        ev = await self._resolve_managed_event(interaction, sortie)
        if ev is None:
            return
        await interaction.response.defer(ephemeral=True)
        async with self._locks[ev.message_id]:
            signup = next((s for s in self.db.get_signups(ev.message_id) if s.user_id == joueur.id), None)
            if signup is None:
                await interaction.followup.send(f"{joueur.mention} n'est pas inscrit.", ephemeral=True)
                return
            self.db.delete_signup(ev.message_id, joueur.id)
            channel = await self._channel(ev.channel_id)
            await self._safe_remove(channel.get_partial_message(ev.message_id), self.emojis[signup.role], joueur.id)
            await self._refresh(ev)
        await interaction.followup.send(f"{joueur.mention} a été retiré de la sortie.", ephemeral=True)

    @event.command(name="liste", description="Lister les prochaines sorties du serveur")
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

    @cancel.autocomplete("sortie")
    @kick.autocomplete("sortie")
    async def _event_autocomplete(self, interaction: discord.Interaction, current: str):
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

    # ============================================================ réactions

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.guild_id is None or payload.user_id == self.bot.user.id:
            return
        if self.db.get_event(payload.message_id) is None:
            return

        async with self._locks[payload.message_id]:
            ev = self.db.get_event(payload.message_id)
            if ev is None:
                return
            try:
                channel = await self._channel(payload.channel_id)
            except discord.HTTPException:
                return
            message = channel.get_partial_message(payload.message_id)
            role = self.emojis.role_for(payload.emoji)
            is_bot = payload.member is not None and payload.member.bot

            # Émote non autorisée, sortie annulée, rôle sans place ou autre bot → on retire.
            if role is None or ev.cancelled or ev.caps[role] <= 0 or is_bot:
                await self._safe_remove(message, payload.emoji, payload.user_id)
                return

            signups = self.db.get_signups(ev.message_id)
            current = next((s.role for s in signups if s.user_id == payload.user_id), None)
            if current == role:
                return

            if sum(1 for s in signups if s.role == role) >= ev.caps[role]:
                await self._safe_remove(message, payload.emoji, payload.user_id)
                await self._notify_full(payload.user_id, ev, role)
                return

            # Inscription (ou changement de rôle : l'ancienne réaction est retirée).
            name = payload.member.display_name if payload.member else None
            self.db.upsert_signup(ev.message_id, payload.user_id, role, name)
            if current is not None:
                await self._safe_remove(message, self.emojis[current], payload.user_id)
            await self._refresh(ev)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.guild_id is None or payload.user_id == self.bot.user.id:
            return
        role = self.emojis.role_for(payload.emoji)
        if role is None or self.db.get_event(payload.message_id) is None:
            return

        async with self._locks[payload.message_id]:
            ev = self.db.get_event(payload.message_id)
            if ev is None or ev.cancelled:
                return
            # On ne désinscrit que si la réaction retirée correspond au rôle enregistré :
            # les réactions que le bot retire lui-même (refus, changement de rôle) sont ignorées.
            current = next((s.role for s in self.db.get_signups(ev.message_id) if s.user_id == payload.user_id), None)
            if current != role:
                return
            self.db.delete_signup(ev.message_id, payload.user_id)
            await self._refresh(ev)

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
        if self.db.get_event(payload.message_id) is not None:
            self.db.delete_event(payload.message_id)
            log.info("Sortie %s supprimée avec son message", payload.message_id)

    @commands.Cog.listener()
    async def on_raw_reaction_clear(self, payload: discord.RawReactionClearEvent) -> None:
        # Un modérateur a vidé toutes les réactions : on remet celles du bot.
        ev = self.db.get_event(payload.message_id)
        if ev is not None and not ev.cancelled:
            async with self._locks[ev.message_id]:
                await self._resync(ev)

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        # Rattrape les réactions ajoutées/retirées pendant que le bot était hors ligne.
        if self._resynced:
            return
        self._resynced = True
        events = self.db.active_events(int(time.time()) - RESYNC_GRACE_SECONDS)
        log.info("Resynchronisation de %d sortie(s) active(s)…", len(events))
        for ev in events:
            async with self._locks[ev.message_id]:
                await self._resync(ev)

    # ============================================================== interne

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

        reacted: dict[str, list[int]] = {r: [] for r in ROLES}
        names: dict[int, str] = {}
        for reaction in message.reactions:
            role = self.emojis.role_for(reaction.emoji)
            if role is None:
                await self._safe_clear(message, reaction.emoji)
                continue
            async for user in reaction.users():
                if user.id != self.bot.user.id:
                    reacted[role].append(user.id)
                    names[user.id] = user.display_name

        signups = {s.user_id: s.role for s in self.db.get_signups(ev.message_id)}
        for uid, role in list(signups.items()):
            if uid not in reacted[role]:
                self.db.delete_signup(ev.message_id, uid)
                del signups[uid]

        counts = Counter(signups.values())
        for role in ROLES:
            for uid in reacted[role]:
                if signups.get(uid) == role:
                    continue
                if uid not in signups and counts[role] < ev.caps[role]:
                    self.db.upsert_signup(ev.message_id, uid, role, names.get(uid))
                    signups[uid] = role
                    counts[role] += 1
                else:
                    await self._safe_remove(message, self.emojis[role], uid)

        await self._refresh(ev)

    async def _refresh(self, ev: Event) -> None:
        """Met à jour l'embed et les réactions du bot (retirées quand un rôle est complet)."""
        try:
            channel = await self._channel(ev.channel_id)
            message = await channel.fetch_message(ev.message_id)
            signups = self.db.get_signups(ev.message_id)
            await message.edit(embed=build_event_embed(ev, signups, self.emojis))
            if ev.cancelled:
                return

            counts = Counter(s.role for s in signups)
            bot_reacted = {self.emojis.role_for(r.emoji) for r in message.reactions if r.me}
            for role in ROLES:
                if ev.caps[role] <= 0:
                    continue
                full = counts[role] >= ev.caps[role]
                if full and role in bot_reacted:
                    await message.remove_reaction(self.emojis[role], self.bot.user)
                elif not full and role not in bot_reacted:
                    await message.add_reaction(self.emojis[role])
        except discord.NotFound:
            self.db.delete_event(ev.message_id)
        except discord.HTTPException as exc:
            log.warning("Mise à jour de la sortie %s impossible : %s", ev.message_id, exc)

    async def _channel(self, channel_id: int):
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            channel = await self.bot.fetch_channel(channel_id)
        return channel

    async def _safe_remove(self, message: discord.PartialMessage | discord.Message, emoji: AnyEmoji, user_id: int) -> None:
        try:
            await message.remove_reaction(emoji, discord.Object(id=user_id))
        except discord.HTTPException as exc:
            log.warning("Impossible de retirer la réaction %s de %s : %s", emoji, user_id, exc)

    async def _safe_clear(self, message: discord.Message, emoji: AnyEmoji) -> None:
        try:
            await message.clear_reaction(emoji)
        except discord.HTTPException as exc:
            log.warning("Impossible de retirer l'émote %s : %s", emoji, exc)

    async def _notify_full(self, user_id: int, ev: Event, role: str) -> None:
        if not self.bot.config.dm_on_refusal:
            return
        try:
            user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
            url = f"https://discord.com/channels/{ev.guild_id}/{ev.channel_id}/{ev.message_id}"
            await user.send(
                f"Désolé, le rôle **{LABELS[role]}** est complet pour **{ev.instance}** "
                f"(<t:{ev.starts_at}:F>). Tu peux t'inscrire dans un autre rôle : {url}"
            )
        except discord.HTTPException:
            pass  # MP fermés : tant pis.

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
