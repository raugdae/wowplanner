"""Priorités de stats (guide WoW Forever de stillsixty.com), pour le site.

Relues par la synchro de nuit et par /admin sync (voir cogs/sync.py). En cas d'échec, on garde les
dernières priorités connues : le site ne perd jamais rien.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

import aiohttp
from discord.ext import commands

from .. import gear, statsource

if TYPE_CHECKING:
    from ..bot import WowPlannerBot

log = logging.getLogger(__name__)


class StatSyncCog(commands.Cog):
    def __init__(self, bot: WowPlannerBot):
        self.bot = bot
        self.db = bot.db

    async def cog_load(self) -> None:
        # Dernières priorités connues, en attendant la prochaine synchro.
        specs, caps, checked = self.db.stat_priorities()
        gear.apply_overrides(specs, caps, checked)

    async def refresh(self) -> bool:
        """Relit le guide et enregistre les priorités ; False (et rien de changé) si ça échoue."""
        try:
            specs, caps = await statsource.fetch(self.bot.http_session)
        except (ValueError, aiohttp.ClientError, asyncio.TimeoutError) as exc:
            log.warning("Priorités de stats non mises à jour : %s", exc)
            return False
        before = {k: v[2] for k, v in gear.PRIORITIES.items()}
        self.db.set_stat_priorities(specs, caps)
        gear.apply_overrides(specs, caps, time.time())
        changed = [k for k, v in gear.PRIORITIES.items() if v[2] != before.get(k)]
        log.info(
            "Priorités de stats relues (%d spés)%s", len(specs),
            f", changées : {', '.join(changed)}" if changed else ", inchangées",
        )
        return True


async def setup(bot: WowPlannerBot) -> None:
    await bot.add_cog(StatSyncCog(bot))
