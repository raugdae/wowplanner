"""Synchro de tout ce qui vient de l'extérieur (wiki, guide, API Blizzard), au même endroit.

- **Chaque nuit à 4 h** (fuseau TIMEZONE) : donjons, priorités de stats, persos ; les arbres de talents
  s'ils ont plus d'une semaine, et seulement les recettes nouvelles. Au démarrage, si la dernière synchro
  date de plus de 20 h (bot éteint pendant la nuit, premier lancement), elle est rattrapée.
- **/admin sync** : la même chose tout de suite, en forçant les talents et toutes les recettes, avec
  l'avancement affiché.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import time as dtime
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable

import discord
from discord.ext import commands, tasks

if TYPE_CHECKING:
    from ..bot import WowPlannerBot

log = logging.getLogger(__name__)

NIGHTLY_AT = dtime(4, 0)
CATCH_UP_AFTER_SECONDS = 20 * 3600

# (icône, texte) d'une étape terminée.
StepResult = tuple[str, str]
Progress = Callable[[list[str]], Awaitable[None]]
OK, WARN, SKIP = "✅", "⚠️", "⏭️"
NO_ARMORY = "armurerie non configurée (clés Blizzard absentes)"


class SyncCog(commands.Cog):
    def __init__(self, bot: WowPlannerBot):
        self.bot = bot
        self._lock = asyncio.Lock()
        self.nightly.change_interval(time=NIGHTLY_AT.replace(tzinfo=bot.config.timezone))

    async def cog_load(self) -> None:
        self.nightly.start()
        asyncio.create_task(self._catch_up())

    async def cog_unload(self) -> None:
        self.nightly.cancel()

    # ============================================================ horaires

    @property
    def _stamp(self) -> Path:
        return Path(self.bot.config.data_dir) / "last_sync"

    def _last_run(self) -> float | None:
        try:
            return float(self._stamp.read_text().strip())
        except (OSError, ValueError):
            return None

    async def _catch_up(self) -> None:
        await self.bot.wait_until_ready()
        last = self._last_run()
        if last is None or time.time() - last > CATCH_UP_AFTER_SECONDS:
            log.info("Synchro de nuit manquée ou jamais faite : rattrapage maintenant")
            await self._nightly_run()

    @tasks.loop(time=NIGHTLY_AT)
    async def nightly(self) -> None:
        await self._nightly_run()

    async def _nightly_run(self) -> None:
        if self._lock.locked():
            log.info("Synchro de nuit sautée : une synchro est déjà en cours")
            return
        async with self._lock:
            lines = await self._run_steps(full=False)
        log.info("Synchro de nuit terminée :\n%s", "\n".join(lines))

    # ============================================================== étapes

    @property
    def _armory(self):
        armory = self.bot.get_cog("ArmoryCog")
        return armory if armory is not None and armory.available else None

    async def _instances(self, full: bool) -> StepResult:
        count = await self.bot.instances.refresh(self.bot.http_session)
        return OK, f"{count} donjons et raids"

    async def _stats(self, full: bool) -> StepResult:
        statsync = self.bot.get_cog("StatSyncCog")
        if statsync is None:
            return SKIP, "module absent"
        if await statsync.refresh():
            return OK, "priorités relues"
        return WARN, "guide injoignable ou modifié, anciennes priorités gardées"

    async def _talents(self, full: bool) -> StepResult:
        armory = self._armory
        if armory is None:
            return SKIP, NO_ARMORY
        trees = await armory.fetch_talent_trees(force=full)
        if trees:
            return OK, f"{trees} arbre(s)"
        # La nuit, rien à faire tant que les arbres ont moins d'une semaine.
        return (WARN, "aucun arbre reçu, anciens gardés") if full else (OK, "déjà à jour (relus chaque semaine)")

    async def _characters(self, full: bool) -> StepResult:
        armory = self._armory
        if armory is None:
            return SKIP, NO_ARMORY
        r = await armory.sync_all()
        if not r.characters:
            return OK, "aucun perso déclaré"
        text = f"{r.found}/{r.characters} trouvé(s)"
        if r.not_found:
            text += f", {r.not_found} introuvable(s) (niveau < 10 ou faute de nom)"
        if r.unreachable:
            text += f", {r.unreachable} sans réponse"
        return (WARN if r.unreachable else OK), text

    async def _recipes(self, full: bool) -> StepResult:
        armory = self._armory
        if armory is None:
            return SKIP, NO_ARMORY
        ids = self.bot.db.all_recipe_ids() if full else self.bot.db.recipes_missing_details()
        if not ids:
            return OK, "aucune recette connue" if full else "rien de nouveau"
        done = await armory.fetch_recipe_details(ids)
        what = "relue(s)" if full else "nouvelle(s) récupérée(s)"
        return (OK if done == len(ids) else WARN), f"{done}/{len(ids)} recette(s) {what}"

    async def _run_steps(self, full: bool, progress: Progress | None = None) -> list[str]:
        """Enchaîne les étapes ; une étape en échec n'empêche pas les suivantes. Renvoie le bilan ligne à ligne."""
        steps: list[tuple[str, Callable[[bool], Awaitable[StepResult]]]] = [
            ("Donjons et raids (wiki)", self._instances),
            ("Priorités de stats (stillsixty)", self._stats),
            ("Arbres de talents (Blizzard)", self._talents),
            ("Persos : métiers, recettes, équipement, talents (armurerie)", self._characters),
            ("Détails des recettes (Blizzard)", self._recipes),
        ]
        lines: list[str] = []
        for label, step in steps:
            lines.append(f"⏳ {label}…")
            if progress:
                await progress(lines)
            try:
                icon, text = await step(full)
            except Exception as exc:
                log.exception("Synchro : échec de « %s »", label)
                icon, text = WARN, f"échec ({exc})"
            lines[-1] = f"{icon} **{label}** : {text}"
        try:
            self._stamp.write_text(str(int(time.time())))
        except OSError as exc:
            log.warning("Impossible de noter l'heure de la synchro : %s", exc)
        return lines

    # ============================================================ /admin sync

    async def run(self, interaction: discord.Interaction) -> None:
        if self._lock.locked():
            await interaction.response.send_message("⏳ Une synchro est déjà en cours.", ephemeral=True)
            return
        async with self._lock:
            await interaction.response.defer(ephemeral=True, thinking=True)
            started = time.monotonic()

            async def progress(lines: list[str]) -> None:
                await self._show(interaction, lines)

            lines = await self._run_steps(full=True, progress=progress)
            minutes, seconds = divmod(int(time.monotonic() - started), 60)
            log.info("/admin sync terminé en %d min %02d s", minutes, seconds)
            await self._show(interaction, lines, done=f"Terminé en {minutes} min {seconds:02d} s.")

    async def _show(self, interaction: discord.Interaction, lines: list[str], done: str | None = None) -> None:
        embed = discord.Embed(
            title="🔄 Synchro complète" + (" terminée" if done else " en cours…"),
            description="\n".join(lines),
            color=0x2ECC71 if done else 0x3498DB,
        )
        if done:
            embed.set_footer(text=done)
        try:
            await interaction.edit_original_response(embed=embed)
        except discord.HTTPException:
            # Discord n'autorise plus la modification après 15 min : le bilan final part en MP.
            if done:
                try:
                    await interaction.user.send(embed=embed)
                except discord.HTTPException:
                    log.info("/admin sync : bilan non transmis (réponse expirée, MP fermés)")


async def setup(bot: WowPlannerBot) -> None:
    await bot.add_cog(SyncCog(bot))
