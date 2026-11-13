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
    event_channel_ids: frozenset[int] = frozenset()
    reminder_minutes: int = 30
    voice_channel_minutes: int = 15
    voice_category_id: int | None = None
    # API Blizzard (armurerie WoW Forever) : facultative, désactivée si vide.
    blizzard_client_id: str = ""
    blizzard_client_secret: str = ""
    blizzard_region: str = "eu"
    # Site web public (persos et métiers, sans info perso). 0 = désactivé.
    web_port: int = 0
    web_host: str = "0.0.0.0"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "wowplanner.db"

    @property
    def instances_cache_path(self) -> Path:
        return self.data_dir / "instances_cache.json"


def load_config() -> Config:
    load_dotenv()

    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        raise SystemExit("DISCORD_TOKEN manquant : copie .env.example en .env et renseigne le token du bot.")

    guild_raw = os.getenv("GUILD_ID", "").strip()
    category_raw = os.getenv("VOICE_CATEGORY_ID", "").strip()
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
        event_channel_ids=frozenset(
            int(cid) for cid in os.getenv("EVENT_CHANNEL_IDS", "").replace(" ", "").split(",") if cid
        ),
        reminder_minutes=int(os.getenv("REMINDER_MINUTES", "30") or 0),
        voice_channel_minutes=int(os.getenv("VOICE_CHANNEL_MINUTES", "15") or 0),
        voice_category_id=int(category_raw) if category_raw else None,
        blizzard_client_id=os.getenv("BLIZZARD_CLIENT_ID", "").strip(),
        blizzard_client_secret=os.getenv("BLIZZARD_CLIENT_SECRET", "").strip(),
        blizzard_region=(os.getenv("BLIZZARD_REGION", "eu").strip() or "eu").lower(),
        web_port=int(os.getenv("WEB_PORT", "0") or 0),
        web_host=os.getenv("WEB_HOST", "0.0.0.0").strip() or "0.0.0.0",
    )
