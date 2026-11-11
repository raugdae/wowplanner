"""Tâches planifiées des sorties : rappel en MP aux inscrits, puis salon vocal temporaire.

Une boucle tourne toutes les minutes. Ce qui a déjà été fait (rappel envoyé, salon créé)
est noté en base : rien n'est envoyé en double, même après un redémarrage du bot.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import TYPE_CHECKING

import discord
from discord.ext import commands, tasks

from ..db import Event
from ..gamedata import class_label
from ..roles import LABELS

if TYPE_CHECKING:
    from ..bot import WowPlannerBot

log = logging.getLogger(__name__)

# Si le bot était hors ligne au moment prévu, le salon vocal est quand même créé
# tant que la sortie a commencé depuis moins de ça.
VOICE_LATE_SECONDS = 3600
# Le salon vocal est supprimé dès qu'il est vide, mais pas avant ce délai après le début de la sortie.
VOICE_KEEP_AFTER_START_SECONDS = 30 * 60

ICONS = {"dungeon": "🗝️", "raid": "🏰"}


class ScheduleCog(commands.Cog):
    def __init__(self, bot: WowPlannerBot):
        self.bot = bot
        self.db = bot.db
        self.config = bot.config

    async def cog_load(self) -> None:
        if self.config.reminder_minutes > 0 or self.config.voice_channel_minutes > 0:
            self.tick.start()

    async def cog_unload(self) -> None:
        self.tick.cancel()

    @tasks.loop(seconds=60)
    async def tick(self) -> None:
        now = int(time.time())
        # Chaque étape est isolée : une erreur sur une sortie ne doit pas bloquer les autres.
        if self.config.reminder_minutes > 0:
            for ev in self.db.events_to_remind(now, self.config.reminder_minutes * 60):
                await self._guarded(self._send_reminder, ev)
        if self.config.voice_channel_minutes > 0:
            for ev in self.db.events_needing_voice(now, self.config.voice_channel_minutes * 60, VOICE_LATE_SECONDS):
                await self._guarded(self._create_voice, ev)
        for ev in self.db.events_with_voice():
            if ev.cancelled or now >= ev.starts_at + VOICE_KEEP_AFTER_START_SECONDS:
                await self._guarded(self.delete_voice_if_empty, ev)

    @tick.before_loop
    async def _before_tick(self) -> None:
        await self.bot.wait_until_ready()

    async def _guarded(self, step, ev: Event) -> None:
        try:
            await step(ev)
        except Exception:
            log.exception("Tâche planifiée %s échouée pour la sortie %s", step.__name__, ev.message_id)

    # ================================================================ rappel

    async def _send_reminder(self, ev: Event) -> None:
        # Marqué avant l'envoi : en cas de plantage au milieu, mieux vaut un rappel manqué qu'en double.
        self.db.mark_reminded(ev.message_id)

        # Sortie créée moins de N minutes avant le début : les inscrits viennent de la voir, pas de rappel.
        if ev.created_at > ev.starts_at - self.config.reminder_minutes * 60:
            return

        url = f"https://discord.com/channels/{ev.guild_id}/{ev.channel_id}/{ev.message_id}"
        voice = ""
        if self.config.voice_channel_minutes > 0:
            voice = f"\nUn salon vocal sera ouvert {self.config.voice_channel_minutes} min avant le départ."

        signups = self.db.get_signups(ev.message_id)
        sent = 0
        for s in signups:
            who = f" avec **{s.character_name}** ({class_label(s.character_class or '')})" if s.character_name else ""
            try:
                user = self.bot.get_user(s.user_id) or await self.bot.fetch_user(s.user_id)
                await user.send(
                    f"⏰ Rappel : **{ev.instance}** commence <t:{ev.starts_at}:R> (<t:{ev.starts_at}:t>).\n"
                    f"Tu es inscrit en **{LABELS[s.role]}**{who}.{voice}\n{url}"
                )
                sent += 1
            except discord.HTTPException:
                pass  # MP fermés : tant pis.
        log.info("Rappel de la sortie %s envoyé à %d/%d inscrit(s)", ev.message_id, sent, len(signups))

    # =========================================================== salon vocal

    async def _create_voice(self, ev: Event) -> None:
        if not self.db.get_signups(ev.message_id):
            return  # personne d'inscrit : on réessaiera à la prochaine minute

        guild = self.bot.get_guild(ev.guild_id)
        if guild is None:
            return

        category = None
        if self.config.voice_category_id:
            category = guild.get_channel(self.config.voice_category_id)
            if not isinstance(category, discord.CategoryChannel):
                log.warning("VOICE_CATEGORY_ID=%s n'est pas une catégorie de ce serveur", self.config.voice_category_id)
                category = None
        if category is None:
            event_channel = guild.get_channel(ev.channel_id)
            category = getattr(event_channel, "category", None)

        hour = datetime.fromtimestamp(ev.starts_at, self.config.timezone).strftime("%Hh%M")
        name = f"{ICONS.get(ev.kind, '👥')} {ev.instance} · {hour}"[:100]
        try:
            channel = await guild.create_voice_channel(
                name,
                category=category,
                user_limit=min(ev.size, 99),
                reason=f"Sortie {ev.instance} (message {ev.message_id})",
            )
        except discord.HTTPException as exc:
            # 0 = on n'essaie plus pour cette sortie (sinon une erreur toutes les minutes).
            self.db.set_voice_channel(ev.message_id, 0)
            log.warning(
                "Création du salon vocal impossible pour %s (permission « Gérer les salons » ?) : %s",
                ev.message_id, exc,
            )
            return

        self.db.set_voice_channel(ev.message_id, channel.id)
        log.info("Salon vocal %s créé pour la sortie %s", channel.id, ev.message_id)
        await self._refresh_message(ev.message_id)

    async def delete_voice_if_empty(self, ev: Event) -> None:
        if not ev.voice_channel_id:
            return
        guild = self.bot.get_guild(ev.guild_id)
        channel = guild.get_channel(ev.voice_channel_id) if guild else None
        if isinstance(channel, discord.VoiceChannel):
            if channel.members:
                return  # encore du monde : on repassera
            try:
                await channel.delete(reason=f"Sortie {ev.instance} terminée ou annulée")
            except discord.NotFound:
                pass
            except discord.HTTPException as exc:
                log.warning("Suppression du salon vocal %s impossible : %s", channel.id, exc)
                return
        # Salon supprimé (par nous ou à la main) : on l'oublie et on retire le lien du message.
        self.db.set_voice_channel(ev.message_id, 0)
        await self._refresh_message(ev.message_id)

    async def _refresh_message(self, message_id: int) -> None:
        events = self.bot.get_cog("EventsCog")
        if events is not None and self.db.get_event(message_id) is not None:
            await events.refresh_event(message_id)


async def setup(bot: WowPlannerBot) -> None:
    await bot.add_cog(ScheduleCog(bot))
