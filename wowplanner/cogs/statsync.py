"""Mise à jour nocturne des priorités de stats (guide WoW Forever de stillsixty.com), pour le site.

Une fois par nuit (4 h, heure du serveur Discord), et au démarrage si la dernière lecture date de plus
d'un jour. En cas d'échec, on garde les dernières priorités connues : le site ne perd jamais rien.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import time as dtime
from typing import TYPE_CHECKING

import aiohttp
from discord.ext import commands, tasks

from .. import gear, statsource

if TYPE_CHECKING:
    from ..bot import WowPlannerBot

log = logging.getLogger(__name__)

STALE_SECONDS = 24 * 3600


class StatSyncCog(commands.Cog):
    def __init__(self, bot: WowPlannerBot):
        self.bot = bot
        self.db = bot.db
        self.nightly.change_interval(time=dtime(4, 0, tzinfo=bot.config.timezone))

    async def cog_load(self) -> None:
        specs, caps, checked = self.db.stat_priorities()
        gear.apply_overrides(specs, caps, checked)
        self.nightly.start()
        asyncio.create_task(self._catch_up(checked))

    async def cog_unload(self) -> None:
        self.nightly.cancel()

    async def _catch_up(self, checked: int | None) -> None:
        await self.bot.wait_until_ready()
        if checked is None or time.time() - checked > STALE_SECONDS:
            await self.refresh()

    @tasks.loop(time=dtime(4, 0))
    async def nightly(self) -> None:
        await self.refresh()

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
