from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    token: str
    guild_id: int | None
    timezone: ZoneInfo
    data_dir: Path
    emoji_tank: str
    emoji_heal: str
    emoji_dps: str
    instances_refresh_hours: float
    dm_on_refusal: bool
    event_channel_ids: frozenset[int] = frozenset()

    @property
    def db_path(self) -> Path:
        return self.data_dir / "wowplanner.db"

    @property
    def instances_cache_path(self) -> Path:
        return self.data_dir / "instances_cache.json"


def _bool(value: str | None, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "oui", "on"}


def load_config() -> Config:
    load_dotenv()

    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        raise SystemExit("DISCORD_TOKEN manquant : copie .env.example en .env et renseigne le token du bot.")

    guild_raw = os.getenv("GUILD_ID", "").strip()
    data_dir = Path(os.getenv("DATA_DIR", "data"))
    data_dir.mkdir(parents=True, exist_ok=True)

    return Config(
        token=token,
        guild_id=int(guild_raw) if guild_raw else None,
        timezone=ZoneInfo(os.getenv("TIMEZONE", "Europe/Paris")),
        data_dir=data_dir,
        emoji_tank=os.getenv("EMOJI_TANK", "🛡️"),
        emoji_heal=os.getenv("EMOJI_HEAL", "⛑️"),
        emoji_dps=os.getenv("EMOJI_DPS", "⚔️"),
        instances_refresh_hours=float(os.getenv("INSTANCES_REFRESH_HOURS", "24")),
        dm_on_refusal=_bool(os.getenv("DM_ON_REFUSAL"), True),
        event_channel_ids=frozenset(
            int(cid) for cid in os.getenv("EVENT_CHANNEL_IDS", "").replace(" ", "").split(",") if cid
        ),
    )
