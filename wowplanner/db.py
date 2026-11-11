"""Persistance SQLite des sorties et des inscriptions (survit aux redémarrages du bot)."""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from .roles import ROLES

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    message_id   INTEGER PRIMARY KEY,
    guild_id     INTEGER NOT NULL,
    channel_id   INTEGER NOT NULL,
    creator_id   INTEGER NOT NULL,
    instance     TEXT    NOT NULL,
    kind         TEXT    NOT NULL,
    levels       TEXT,
    starts_at    INTEGER NOT NULL,
    tank_cap     INTEGER NOT NULL,
    heal_cap     INTEGER NOT NULL,
    dps_cap      INTEGER NOT NULL,
    description  TEXT,
    cancelled    INTEGER NOT NULL DEFAULT 0,
    created_at   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_guild_start ON events (guild_id, starts_at);

CREATE TABLE IF NOT EXISTS signups (
    message_id INTEGER NOT NULL REFERENCES events (message_id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL,
    role       TEXT    NOT NULL,
    signed_at  REAL    NOT NULL,
    display_name TEXT,
    PRIMARY KEY (message_id, user_id)
);
"""


@dataclass
class Event:
    message_id: int
    guild_id: int
    channel_id: int
    creator_id: int
    instance: str
    kind: str  # "dungeon" | "raid" | "custom"
    levels: str | None
    starts_at: int  # timestamp unix
    caps: dict[str, int]
    description: str | None = None
    cancelled: bool = False
    created_at: int = field(default_factory=lambda: int(time.time()))

    @property
    def size(self) -> int:
        return sum(self.caps.values())


@dataclass
class Signup:
    user_id: int
    role: str
    signed_at: float
    display_name: str | None = None


class Database:
    def __init__(self, path: Path):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        # v1.0 → v1.1 : pseudo affiché des inscrits.
        columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(signups)")}
        if "display_name" not in columns:
            self.conn.execute("ALTER TABLE signups ADD COLUMN display_name TEXT")

    def close(self) -> None:
        self.conn.close()

    # ------------------------------------------------------------------ events

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> Event:
        return Event(
            message_id=row["message_id"],
            guild_id=row["guild_id"],
            channel_id=row["channel_id"],
            creator_id=row["creator_id"],
            instance=row["instance"],
            kind=row["kind"],
            levels=row["levels"],
            starts_at=row["starts_at"],
            caps={"tank": row["tank_cap"], "heal": row["heal_cap"], "dps": row["dps_cap"]},
            description=row["description"],
            cancelled=bool(row["cancelled"]),
            created_at=row["created_at"],
        )

    def create_event(self, ev: Event) -> None:
        with self.conn:
            self.conn.execute(
                """INSERT INTO events (message_id, guild_id, channel_id, creator_id, instance, kind, levels,
                                       starts_at, tank_cap, heal_cap, dps_cap, description, cancelled, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ev.message_id, ev.guild_id, ev.channel_id, ev.creator_id, ev.instance, ev.kind, ev.levels,
                    ev.starts_at, ev.caps["tank"], ev.caps["heal"], ev.caps["dps"], ev.description,
                    int(ev.cancelled), ev.created_at,
                ),
            )

    def get_event(self, message_id: int) -> Event | None:
        row = self.conn.execute("SELECT * FROM events WHERE message_id = ?", (message_id,)).fetchone()
        return self._row_to_event(row) if row else None

    def upcoming_events(self, guild_id: int, after: int) -> list[Event]:
        rows = self.conn.execute(
            "SELECT * FROM events WHERE guild_id = ? AND cancelled = 0 AND starts_at >= ? ORDER BY starts_at",
            (guild_id, after),
        ).fetchall()
        return [self._row_to_event(r) for r in rows]

    def active_events(self, after: int) -> list[Event]:
        rows = self.conn.execute(
            "SELECT * FROM events WHERE cancelled = 0 AND starts_at >= ? ORDER BY starts_at", (after,)
        ).fetchall()
        return [self._row_to_event(r) for r in rows]

    def set_cancelled(self, message_id: int) -> None:
        with self.conn:
            self.conn.execute("UPDATE events SET cancelled = 1 WHERE message_id = ?", (message_id,))

    def delete_event(self, message_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM events WHERE message_id = ?", (message_id,))

    # ----------------------------------------------------------------- signups

    def get_signups(self, message_id: int) -> list[Signup]:
        rows = self.conn.execute(
            "SELECT user_id, role, signed_at, display_name FROM signups WHERE message_id = ? ORDER BY signed_at",
            (message_id,),
        ).fetchall()
        return [
            Signup(r["user_id"], r["role"], r["signed_at"], r["display_name"]) for r in rows if r["role"] in ROLES
        ]

    def upsert_signup(self, message_id: int, user_id: int, role: str, display_name: str | None) -> None:
        with self.conn:
            self.conn.execute(
                """INSERT INTO signups (message_id, user_id, role, signed_at, display_name) VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT (message_id, user_id) DO UPDATE SET role = excluded.role,
                                                                   signed_at = excluded.signed_at,
                                                                   display_name = excluded.display_name""",
                (message_id, user_id, role, time.time(), display_name),
            )

    def delete_signup(self, message_id: int, user_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM signups WHERE message_id = ? AND user_id = ?", (message_id, user_id))
