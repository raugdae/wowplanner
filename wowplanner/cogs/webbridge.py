"""Actions du site (sorties, persos) exécutées par le bot : le site ne parle jamais à Discord lui-même.

Une sortie créée ou modifiée sur le site passe par EventsCog, comme depuis Discord : message posté dans le
salon des sorties, boutons et liste des inscrits mis à jour. Inversement, le site relit la base à chaque
page : ce qui est fait sur Discord y apparaît au rechargement.

Les persos ajoutés depuis le site doivent exister dans l'armurerie (vérifiés au fil de la frappe, puis à
l'ajout) ; classe, race et niveau en sont repris.
"""
from __future__ import annotations

import asyncio
import logging
import re
import sqlite3
import time
from typing import TYPE_CHECKING, Any

import discord
from discord.ext import commands

from ..armory import character_slug
from ..db import SOURCE_WEB, Character, Event, Order
from ..gamedata import CLASSES, RACES, can_play, class_label, race_allows, race_label, roles_for
from ..gear import parse_equipment
from ..orders import STATUS_LABELS, TRANSITIONS, Candidate, allowed_actions
from ..recipes import crafted_by_map
from ..roles import LABELS, ROLES
from ..webmember import ActionError, WebUser
from .armory import NOT_FOUND_HELP
from .characters import MAX_CHARACTERS, NAME_ERROR, normalize_name, race_refusal, role_refusal

if TYPE_CHECKING:
    from ..bot import WowPlannerBot
    from .armory import ArmoryCog
    from .events import EventsCog

log = logging.getLogger(__name__)

# Réponses de l'armurerie pour la vérification au fil de la frappe (un nom tapé lettre par lettre).
LOOKUP_CACHE_SECONDS = 300
LOOKUP_CACHE_MAX = 500
# Droit de gérer une sortie (organisateur ou modo) : gardé quelques minutes pour ne pas interroger Discord
# à chaque affichage de la page.
MANAGE_CACHE_SECONDS = 300
# Droits d'administration (« Gérer le serveur ») : revérifiés toutes les 5 minutes.
ADMIN_CACHE_SECONDS = 300
# Pseudos des membres (page d'administration).
NAME_CACHE_SECONDS = 3600


class WebBridge(commands.Cog):
    def __init__(self, bot: WowPlannerBot):
        self.bot = bot
        self.db = bot.db
        self.timezone = bot.config.timezone
        self._lookups: dict[str, tuple[float, dict[str, Any]]] = {}
        self._managers: dict[tuple[int, int], tuple[float, bool]] = {}
        self._admins: dict[int, tuple[float, bool]] = {}
        self._names: dict[int, tuple[float, str]] = {}
        # Dernière synchro lancée depuis le site : {"by", "started", "finished", "lines", "running"}.
        self.sync_state: dict[str, Any] | None = None
        self._sync_task: asyncio.Task | None = None

    async def cog_load(self) -> None:
        self.bot.website.enable_actions(self)

    # ================================================================ outils

    @property
    def events(self) -> EventsCog:
        cog = self.bot.get_cog("EventsCog")
        if cog is None:
            raise ActionError("Les sorties sont indisponibles pour l'instant.")
        return cog  # type: ignore[return-value]

    @property
    def armory(self) -> ArmoryCog | None:
        cog = self.bot.get_cog("ArmoryCog")
        return cog if cog is not None and cog.available else None  # type: ignore[return-value]

    @property
    def armory_enabled(self) -> bool:
        return self.armory is not None

    def _guild_id(self) -> int:
        gid = self.bot.website.guild_id()
        if gid is None:
            raise ActionError("Serveur Discord non déterminé (GUILD_ID).")
        return gid

    def _event(self, message_id: int) -> Event:
        ev = self.db.get_event(message_id)
        if ev is None or ev.guild_id != self._guild_id():
            raise ActionError("Cette sortie n'existe plus.")
        return ev

    # ================================================================ sorties

    def event_channels(self) -> list[tuple[int, str]]:
        """Salons où le site peut poster une sortie : EVENT_CHANNEL_IDS, sinon celui de la dernière sortie."""
        ids = list(self.bot.config.event_channel_ids)
        if not ids:
            try:
                last = self.db.last_event_channel(self._guild_id())
            except ActionError:
                last = None
            ids = [last] if last else []
        channels = []
        for cid in sorted(ids):
            channel = self.bot.get_channel(cid)
            if channel is not None:
                channels.append((cid, f"#{channel.name}"))
        return channels

    def instance_options(self) -> list[tuple[str, str]]:
        """(valeur, libellé) des donjons et raids connus, pour la saisie de l'instance."""
        return [(i.name, i.choice_label()) for i in self.bot.instances.all]

    def match_instance(self, *names: str) -> str | None:
        """Nom dans la liste des instances (wiki) d'un donjon de la page Donjons (« The Deadmines » → « Deadmines »,
        « Sunken Temple » → « Temple of Atal'Hakkar (Sunken Temple) »). None si rien ne correspond."""
        def keys(text: str) -> set[str]:
            text = text.lower().replace("’", "'")
            inside = re.findall(r"\((.*?)\)", text)
            outside = re.sub(r"\(.*?\)", "", text)
            return {re.sub(r"^the\s+", "", k.strip()) for k in [outside, *inside] if k.strip()}

        wanted = set().union(*(keys(n) for n in names if n))
        for inst in self.bot.instances.all:
            if keys(inst.name) & wanted:
                return inst.name
        return None

    async def create_event(
        self, user: WebUser, channel_id: int | None, instance: str, date: str, heure: str,
        joueurs: int | None, tanks: int | None, heals: int | None, dps: int | None, description: str | None,
    ) -> str:
        channels = dict(self.event_channels())
        if not channels:
            raise ActionError(
                "Aucun salon de sorties connu : crée la première sortie sur Discord (ou renseigne EVENT_CHANNEL_IDS)."
            )
        if channel_id is None and len(channels) == 1:
            channel_id = next(iter(channels))
        if channel_id not in channels:
            raise ActionError("Choisis le salon où poster la sortie.")
        events = self.events
        channel = self.bot.get_channel(channel_id)
        problem = events.channel_problem(channel)
        if problem:
            raise ActionError(problem)
        try:
            ev = events.prepare_event(
                self._guild_id(), channel_id, user, instance, date, heure, joueurs, tanks, heals, dps, description
            )
        except ValueError as exc:
            raise ActionError(str(exc)) from None
        try:
            await events.publish_event(ev, channel)  # type: ignore[arg-type]
        except discord.HTTPException as exc:
            log.warning("Sortie du site non publiée : %s", exc)
            raise ActionError("Discord a refusé le message de la sortie. Réessaie dans un moment.") from None
        self.db.touch_member(ev.guild_id, user.id)
        log.info("Sortie créée depuis le site par %s : %s", user.display_name, ev.instance)
        return f"✅ Sortie **{ev.instance}** du <t:{ev.starts_at}:F> créée et postée sur Discord.{events.size_warning(ev)}"

    async def signup(self, user: WebUser, message_id: int, role: str, character_id: int | None) -> str:
        ev = self._event(message_id)
        if role not in ROLES:
            raise ActionError("Rôle inconnu.")
        if ev.cancelled or ev.caps[role] <= 0:
            raise ActionError("Cette sortie n'est plus ouverte à ce rôle.")
        mine = self.db.get_characters(user.id)
        character = next((c for c in mine if c.id == character_id), None) if character_id else None
        if character_id and character is None:
            raise ActionError("Ce perso n'est pas à toi.")
        if character is None and mine:
            raise ActionError("Choisis le perso avec lequel tu t'inscris.")
        if character is not None and not can_play(character.wow_class, role):
            raise ActionError(role_refusal(character.wow_class, role).removeprefix("⚠️ "))
        self.db.touch_member(ev.guild_id, user.id)
        changed, text = await self.events.register(message_id, user, role, character)  # type: ignore[arg-type]
        if changed:
            await self.events.refresh_event(message_id)
            return text
        raise ActionError(text)

    async def leave(self, user: WebUser, message_id: int) -> str:
        ev = self._event(message_id)
        if await self.events.leave(message_id, user.id) is None:
            raise ActionError("Tu n'es pas inscrit à cette sortie.")
        return f"Tu es désinscrit de **{ev.instance}**."

    async def can_manage(self, user_id: int, ev: Event) -> bool:
        if user_id == ev.creator_id or await self.is_admin(user_id):
            return True
        key = (user_id, ev.channel_id)
        cached = self._managers.get(key)
        if cached and time.monotonic() - cached[0] < MANAGE_CACHE_SECONDS:
            return cached[1]
        events = self.bot.get_cog("EventsCog")
        if events is None:
            return False
        allowed = await events.can_manage(user_id, ev)  # type: ignore[attr-defined]
        self._managers[key] = (time.monotonic(), allowed)
        return allowed

    async def _managed(self, user: WebUser, message_id: int) -> Event:
        ev = self._event(message_id)
        if ev.cancelled:
            raise ActionError("Cette sortie est déjà annulée.")
        if not await self.can_manage(user.id, ev):
            raise ActionError("Seul l'organisateur ou un modérateur peut faire ça.")
        return ev

    async def cancel(self, user: WebUser, message_id: int) -> str:
        ev = await self._managed(user, message_id)
        log.info("Sortie %s annulée depuis le site par %s", ev.message_id, user.display_name)
        return await self.events.do_cancel(ev.message_id)

    async def kick(self, user: WebUser, message_id: int, target_id: int) -> str:
        ev = await self._managed(user, message_id)
        signup = next((s for s in self.db.get_signups(ev.message_id) if s.user_id == target_id), None)
        if signup is None or not await self.events.remove_signup(ev, target_id):
            raise ActionError("Ce joueur n'est plus inscrit.")
        who = signup.character_name or signup.display_name or "Le joueur"
        return f"**{who}** a été désinscrit de **{ev.instance}**."

    # ================================================================== persos

    async def armory_lookup(self, user_id: int, raw_name: str) -> dict[str, Any]:
        """Vérification d'un nom pendant la saisie : {"status": "found" | "not_found" | "invalid" | "unreachable"
        | "disabled" | "duplicate", …}."""
        name = normalize_name(raw_name)
        if name is None:
            return {"status": "invalid", "text": NAME_ERROR.removeprefix("⚠️ ").replace("**", "").replace("`", "")}
        if any(c.name.lower() == name.lower() for c in self.db.get_characters(user_id)):
            return {"status": "duplicate", "name": name}
        armory = self.armory
        if armory is None:
            return {"status": "disabled", "name": name}
        slug = character_slug(name)
        cached = self._lookups.get(slug)
        if cached and time.monotonic() - cached[0] < LOOKUP_CACHE_SECONDS:
            return cached[1]
        sheet, found = await armory.lookup(name)
        if sheet is not None and sheet.class_key and sheet.race_key:
            result = {
                "status": "found", "name": sheet.full_name or name, "level": sheet.level,
                "class": class_label(sheet.class_key), "class_key": sheet.class_key, "race": race_label(sheet.race_key),
                "roles": [[r, LABELS[r]] for r in roles_for(sheet.class_key)],
            }
        elif found is None:
            return {"status": "unreachable", "name": name}  # pas de cache : on réessaiera
        else:
            result = {"status": "not_found", "name": name}
        if len(self._lookups) > LOOKUP_CACHE_MAX:
            self._lookups.clear()
        self._lookups[slug] = (time.monotonic(), result)
        return result

    async def add_character(
        self, user: WebUser, raw_name: str, role: str | None, wow_class: str | None = None, race: str | None = None,
        owner_id: int | None = None,
    ) -> str:
        """Ajoute un perso au joueur, ou (admin) au membre `owner_id`, qui est alors prévenu en MP."""
        owner = owner_id or user.id
        by_admin = owner != user.id
        if by_admin:
            await self._require_admin(user)
        has = "Ce membre a" if by_admin else "Tu as"
        name = normalize_name(raw_name)
        if name is None:
            raise ActionError(NAME_ERROR.removeprefix("⚠️ "))
        existing = self.db.get_characters(owner)
        if len(existing) >= MAX_CHARACTERS:
            raise ActionError(f"{has} déjà {MAX_CHARACTERS} persos (maximum).")
        if any(c.name.lower() == name.lower() for c in existing):
            raise ActionError(f"{has} déjà un perso nommé **{name}**.")

        armory = self.armory
        sheet = None
        if armory is not None:
            # Vérification obligatoire : le perso doit exister (fiche complète, pour le site tout de suite).
            sheet, found = await armory.fetch(name, max_age=0)
            if sheet is None:
                if found is False:
                    raise ActionError(f"**{name}** est introuvable dans l'armurerie. {NOT_FOUND_HELP}")
                raise ActionError("L'armurerie ne répond pas pour l'instant : réessaie dans un moment.")
            wow_class, race = sheet.class_key, sheet.race_key
            if not wow_class or not race:
                raise ActionError("Classe ou race inconnue dans l'armurerie : ajoute ce perso depuis Discord.")
        else:
            # Sans clés Blizzard : déclaration à la main, comme sur Discord.
            if wow_class not in CLASSES or race not in RACES:
                raise ActionError("Précise la classe et la race.")
            if not race_allows(race, wow_class):
                raise ActionError(race_refusal(race, wow_class).removeprefix("⚠️ "))
        if role and role not in roles_for(wow_class):
            raise ActionError(role_refusal(wow_class, role).removeprefix("⚠️ "))

        try:
            character = self.db.add_character(owner, name, wow_class, race, role or None, source=SOURCE_WEB)
        except sqlite3.IntegrityError:
            raise ActionError(f"{has} déjà un perso nommé **{name}**.") from None
        self.db.touch_member(self._guild_id(), owner)
        if armory is not None and sheet is not None:
            armory.apply(character, sheet)
            await armory.fetch_item_icons({i["id"] for i in parse_equipment(sheet.equipment) or []})
        log.info("Perso ajouté depuis le site : %s (joueur %s, par %s)", name, owner, user.id)
        level = f", niveau {sheet.level}" if sheet is not None and sheet.level else ""
        what = f"**{name}** ({class_label(wow_class)} {race_label(race)}{level})"
        if by_admin:
            await self._tell(owner, f"🛠️ **{user.display_name}** a ajouté ton perso {what} sur le site.")
            return f"✅ {what} ajouté pour **{(await self.member_names([owner]))[owner]}**."
        return f"✅ {what} ajouté."

    async def _character_for(self, user: WebUser, character_id: int) -> tuple[Character, bool]:
        """(perso, géré par un admin ?) : le perso du joueur, ou celui d'un autre si le joueur est admin."""
        character = self.db.get_character(character_id)
        if character is None:
            raise ActionError("Ce perso n'existe plus.")
        if character.user_id == user.id:
            return character, False
        if await self.is_admin(user.id) and character.user_id in self.db.guild_member_ids(self._guild_id()):
            return character, True
        raise ActionError("Ce perso n'est pas à toi.")

    async def delete_character(self, user: WebUser, character_id: int) -> str:
        character, by_admin = await self._character_for(user, character_id)
        affected = self.db.delete_character(character.user_id, character.id)
        for message_id in affected:  # les sorties où il était inscrit affichent désormais le pseudo
            await self.events.refresh_event(message_id)
        if by_admin:
            log.info("Perso %s supprimé depuis le site par l'admin %s", character.name, user.id)
            await self._tell(character.user_id, f"🛠️ **{user.display_name}** a supprimé ton perso **{character.name}** du bot.")
        return f"🗑️ **{character.name}** supprimé, avec ses métiers."

    async def set_role(self, user: WebUser, character_id: int, role: str | None) -> str:
        character, _ = await self._character_for(user, character_id)
        if role and role not in roles_for(character.wow_class):
            raise ActionError(role_refusal(character.wow_class, role).removeprefix("⚠️ "))
        self.db.set_preferred_role(character.id, role or None)
        text = f"rôle préféré : **{LABELS[role]}**" if role else "plus de rôle préféré"
        return f"✅ **{character.name}** : {text}."

    async def set_favorite(self, user: WebUser, character_id: int) -> str:
        """Perso préféré du joueur ; le choisir à nouveau le retire."""
        character, _ = await self._character_for(user, character_id)
        if character.user_id != user.id:
            raise ActionError("Ce perso n'est pas à toi.")
        if character.favorite:
            self.db.set_favorite(user.id, None)
            return f"**{character.name}** n'est plus ton perso préféré."
        self.db.set_favorite(user.id, character.id)
        return f"⭐ **{character.name}** est ton perso préféré : il est proposé en premier pour t'inscrire."

    # ================================================================== atelier

    def orderable(self, user_id: int) -> list[Candidate]:
        """Recettes que le joueur peut commander (connues d'au moins un perso d'un autre joueur)."""
        cog = self.bot.get_cog("OrdersCog")
        return cog.candidates(self._guild_id(), user_id) if cog is not None else []  # type: ignore[attr-defined]

    def user_orders(self, user_id: int) -> list[Order]:
        return self.db.user_orders(user_id, closed_limit=10)

    def crafted_by(self) -> Any:
        return crafted_by_map(self.db.guild_recipes(self._guild_id()))

    async def place_order(
        self, user: WebUser, recipe_id: int, crafter_character_id: int, quantity: int, note: str | None,
    ) -> str:
        cog = self.bot.get_cog("OrdersCog")
        if cog is None:
            raise ActionError("L'atelier est indisponible pour l'instant.")
        gid = self._guild_id()
        try:
            order = cog.build_order(  # type: ignore[attr-defined]
                gid, user.id, user.display_name, recipe_id, crafter_character_id, quantity, note,
            )
        except ValueError as exc:
            raise ActionError(str(exc)) from None
        order = self.db.create_order(order)
        self.db.touch_member(gid, user.id)
        delivered = await cog.notify_new(order)  # type: ignore[attr-defined]
        log.info("Commande #%s passée depuis le site par %s", order.id, user.display_name)
        if not delivered:
            return (
                f"📨 Commande **#{order.id}** enregistrée, mais **{order.crafter_name}** n'accepte pas les MP du bot : "
                "préviens l'artisan, la commande est aussi dans son atelier sur le site."
            )
        return f"📨 Commande **#{order.id}** envoyée à **{order.crafter_name}** (en MP). Tu seras prévenu de sa réponse."

    async def order_action(self, user: WebUser, order_id: int, action: str) -> str:
        cog = self.bot.get_cog("OrdersCog")
        order = self.db.get_order(order_id)
        if cog is None or order is None or order.guild_id != self._guild_id():
            raise ActionError("Cette commande n'existe plus.")
        if action not in TRANSITIONS or action not in allowed_actions(order, user.id):
            raise ActionError(f"Impossible : la commande **#{order.id}** est déjà « {STATUS_LABELS[order.status]} ».")
        order, done = cog.transition(order, action)  # type: ignore[attr-defined]
        if not done:
            raise ActionError(f"La commande **#{order.id}** a changé entre-temps : {STATUS_LABELS[order.status]}.")
        await cog.after_transition(order, action)  # type: ignore[attr-defined]
        return f"Commande **#{order.id}** ({order.quantity}× {order.recipe_name}) : {STATUS_LABELS[order.status]}."

    # ========================================================== administration

    async def is_admin(self, user_id: int) -> bool:
        """Permission « Gérer le serveur » sur Discord, comme pour les commandes /admin."""
        cached = self._admins.get(user_id)
        if cached and time.monotonic() - cached[0] < ADMIN_CACHE_SECONDS:
            return cached[1]
        gid = self.bot.website.guild_id()
        guild = self.bot.get_guild(gid) if gid else None
        if guild is None:
            return False
        try:
            member = guild.get_member(user_id) or await guild.fetch_member(user_id)
        except discord.HTTPException:
            return False  # pas mis en cache : Discord peut répondre au prochain essai
        allowed = bool(member.guild_permissions.manage_guild)
        self._admins[user_id] = (time.monotonic(), allowed)
        return allowed

    async def _require_admin(self, user: WebUser) -> None:
        if not await self.is_admin(user.id):
            raise ActionError("Réservé aux membres qui ont la permission « Gérer le serveur » sur Discord.")

    async def member_names(self, user_ids: list[int]) -> dict[int, str]:
        """Pseudo de chaque membre sur le serveur (« a quitté le serveur » s'il n'y est plus)."""
        gid = self.bot.website.guild_id()
        guild = self.bot.get_guild(gid) if gid else None
        now = time.monotonic()
        names: dict[int, str] = {}
        for uid in dict.fromkeys(user_ids):
            cached = self._names.get(uid)
            if cached and now - cached[0] < NAME_CACHE_SECONDS:
                names[uid] = cached[1]
                continue
            name = None
            if guild is not None:
                try:
                    member = guild.get_member(uid) or await guild.fetch_member(uid)
                    name = member.display_name
                except discord.NotFound:
                    name = f"{self.db.last_display_name(uid) or 'Joueur'} (a quitté le serveur)"
                except discord.HTTPException:
                    pass
            if name is None:  # Discord injoignable : pas mis en cache
                names[uid] = self.db.last_display_name(uid) or f"Joueur …{str(uid)[-4:]}"
                continue
            self._names[uid] = (now, name)
            names[uid] = name
        return names

    async def start_sync(self, user: WebUser) -> str:
        """Lance la synchro complète (comme /admin sync) en tâche de fond ; la page d'admin affiche l'avancement."""
        await self._require_admin(user)
        sync = self.bot.get_cog("SyncCog")
        if sync is None:
            raise ActionError("Module de synchro absent.")
        if sync.busy:  # type: ignore[attr-defined]
            raise ActionError("Une synchro est déjà en cours.")
        state: dict[str, Any] = {"by": user.display_name, "started": time.time(), "finished": None, "lines": [],
                                 "running": True}
        self.sync_state = state

        async def progress(lines: list[str]) -> None:
            state["lines"] = list(lines)

        async def job() -> None:
            try:
                lines = await sync.run_full(progress)  # type: ignore[attr-defined]
                if lines is None:
                    state["lines"] = ["⚠️ Une synchro était déjà en cours."]
                else:
                    state["lines"] = lines
            except Exception:
                log.exception("Synchro lancée depuis le site en échec")
                state["lines"] = state["lines"] + ["⚠️ Synchro interrompue par une erreur (voir les logs)."]
            finally:
                state["running"] = False
                state["finished"] = time.time()

        self._sync_task = asyncio.create_task(job())
        log.info("Synchro complète lancée depuis le site par %s", user.display_name)
        return "🔄 Synchro complète lancée : l'avancement s'affiche ci-dessous (recharge la page)."

    def last_sync(self) -> float | None:
        sync = self.bot.get_cog("SyncCog")
        return sync.last_run() if sync is not None else None  # type: ignore[attr-defined]

    async def _tell(self, user_id: int, text: str) -> None:
        """MP au joueur quand un admin touche à ses persos (silencieux si ses MP sont fermés)."""
        try:
            target = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
            await target.send(text)
        except discord.HTTPException:
            pass


async def setup(bot: WowPlannerBot) -> None:
    await bot.add_cog(WebBridge(bot))
