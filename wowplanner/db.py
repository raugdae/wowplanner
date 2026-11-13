"""Persistance SQLite des sorties et des inscriptions (survit aux redémarrages du bot)."""
from __future__ import annotations

import json
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
    created_at   INTEGER NOT NULL,
    reminder_sent    INTEGER NOT NULL DEFAULT 0,
    voice_channel_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_events_guild_start ON events (guild_id, starts_at);

CREATE TABLE IF NOT EXISTS characters (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    name       TEXT    NOT NULL,
    wow_class  TEXT    NOT NULL,
    race       TEXT    NOT NULL,
    preferred_role TEXT,
    created_at INTEGER NOT NULL,
    UNIQUE (user_id, name COLLATE NOCASE)
);

CREATE TABLE IF NOT EXISTS character_professions (
    character_id INTEGER NOT NULL REFERENCES characters (id) ON DELETE CASCADE,
    profession   TEXT    NOT NULL,
    skill        INTEGER,
    PRIMARY KEY (character_id, profession)
);

-- Recettes vues dans l'armurerie. Nom français et composants récupérés une seule fois (données statiques).
CREATE TABLE IF NOT EXISTS recipes (
    id         INTEGER PRIMARY KEY,
    profession TEXT    NOT NULL,
    name_en    TEXT    NOT NULL,
    name       TEXT,
    reagents   TEXT,
    fetched_at INTEGER
);

CREATE TABLE IF NOT EXISTS character_recipes (
    character_id INTEGER NOT NULL REFERENCES characters (id) ON DELETE CASCADE,
    recipe_id    INTEGER NOT NULL REFERENCES recipes (id),
    PRIMARY KEY (character_id, recipe_id)
);

CREATE TABLE IF NOT EXISTS players (
    user_id    INTEGER PRIMARY KEY,
    battletag  TEXT,
    updated_at INTEGER NOT NULL
);

-- Joueurs vus sur chaque serveur : les listes (BattleTag, métiers) ne montrent que les membres du serveur.
CREATE TABLE IF NOT EXISTS guild_members (
    guild_id INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS signups (
    message_id INTEGER NOT NULL REFERENCES events (message_id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL,
    role       TEXT    NOT NULL,
    signed_at  REAL    NOT NULL,
    display_name TEXT,
    character_id INTEGER REFERENCES characters (id) ON DELETE SET NULL,
    PRIMARY KEY (message_id, user_id)
);

-- Commandes d'objets à fabriquer, passées à un perso qui connaît la recette.
CREATE TABLE IF NOT EXISTS orders (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id         INTEGER NOT NULL,
    requester_id     INTEGER NOT NULL,
    requester_name   TEXT    NOT NULL,
    recipe_id        INTEGER NOT NULL,
    recipe_name      TEXT    NOT NULL,
    quantity         INTEGER NOT NULL,
    reagents_text    TEXT,
    note             TEXT,
    crafter_character_id INTEGER REFERENCES characters (id) ON DELETE SET NULL,
    crafter_name     TEXT    NOT NULL,
    crafter_user_id  INTEGER NOT NULL,
    status           TEXT    NOT NULL DEFAULT 'pending',
    created_at       INTEGER NOT NULL,
    updated_at       INTEGER NOT NULL,
    crafter_dm_channel_id INTEGER,
    crafter_dm_message_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_orders_requester ON orders (requester_id);
CREATE INDEX IF NOT EXISTS idx_orders_crafter ON orders (crafter_user_id);
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
    reminder_sent: bool = False
    # None : pas encore créé · 0 : supprimé ou création impossible · >0 : ID du salon vocal
    voice_channel_id: int | None = None

    @property
    def size(self) -> int:
        return sum(self.caps.values())


@dataclass
class Signup:
    user_id: int
    role: str
    signed_at: float
    display_name: str | None = None
    character_id: int | None = None
    character_name: str | None = None
    character_class: str | None = None


@dataclass
class Character:
    id: int
    user_id: int
    name: str
    wow_class: str
    race: str
    preferred_role: str | None = None
    # métier -> niveau (None si non renseigné)
    professions: dict[str, int | None] = field(default_factory=dict)
    # Dernière synchro réussie avec l'armurerie (timestamp), None si jamais trouvé.
    armory_synced_at: int | None = None


# Version du format des détails de recette ; une recette plus ancienne est redemandée à Blizzard.
# 2 : identifiants des composants et de l'objet fabriqué (pour relier les sous-recettes).
RECIPE_DETAILS_VERSION = 2


@dataclass
class GuildRecipe:
    id: int
    name: str
    reagents: list[tuple[int, str, int | None]] | None  # (qté, nom, id objet) ; None : pas encore récupérés
    crafters: list[str]  # noms des persos qui la connaissent
    crafted_item_id: int | None = None
    crafted_quantity: float = 1.0


@dataclass
class Crafter:
    """Un perso d'un membre du serveur qui connaît une recette."""
    character_id: int
    name: str
    user_id: int
    wow_class: str


ORDER_ACTIVE = ("pending", "accepted")


@dataclass
class Order:
    guild_id: int
    requester_id: int
    requester_name: str
    recipe_id: int
    recipe_name: str
    quantity: int
    crafter_character_id: int | None
    crafter_name: str
    crafter_user_id: int
    reagents_text: str | None = None
    note: str | None = None
    status: str = "pending"  # pending | accepted | done | refused | cancelled
    created_at: int = field(default_factory=lambda: int(time.time()))
    updated_at: int = field(default_factory=lambda: int(time.time()))
    crafter_dm_channel_id: int | None = None
    crafter_dm_message_id: int | None = None
    id: int = 0

    @property
    def active(self) -> bool:
        return self.status in ORDER_ACTIVE


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
        # v1.2 → v1.3 : personnage joué.
        if "character_id" not in columns:
            self.conn.execute(
                "ALTER TABLE signups ADD COLUMN character_id INTEGER REFERENCES characters (id) ON DELETE SET NULL"
            )
        # v1.1 → v1.2 : rappel en MP et salon vocal automatique.
        columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(events)")}
        if "reminder_sent" not in columns:
            self.conn.execute("ALTER TABLE events ADD COLUMN reminder_sent INTEGER NOT NULL DEFAULT 0")
        if "voice_channel_id" not in columns:
            self.conn.execute("ALTER TABLE events ADD COLUMN voice_channel_id INTEGER")
        # v1.3 → v1.4 : synchro des métiers depuis l'armurerie.
        columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(characters)")}
        if "armory_synced_at" not in columns:
            self.conn.execute("ALTER TABLE characters ADD COLUMN armory_synced_at INTEGER")
        # v1.4 → v1.5 : liens entre recettes (composant fabriqué par une autre recette).
        columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(recipes)")}
        for column in ("crafted_item_id INTEGER", "crafted_qty REAL", "details_version INTEGER"):
            if column.split()[0] not in columns:
                self.conn.execute(f"ALTER TABLE recipes ADD COLUMN {column}")
        # Les joueurs déjà inscrits à des sorties sont membres du serveur de ces sorties.
        self.conn.execute(
            """INSERT OR IGNORE INTO guild_members (guild_id, user_id)
               SELECT DISTINCT e.guild_id, s.user_id FROM signups s JOIN events e ON e.message_id = s.message_id"""
        )

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
            reminder_sent=bool(row["reminder_sent"]),
            voice_channel_id=row["voice_channel_id"],
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

    def events_to_remind(self, now: int, lead: int) -> list[Event]:
        """Sorties qui commencent dans moins de `lead` secondes et dont le rappel n'est pas parti."""
        rows = self.conn.execute(
            """SELECT * FROM events WHERE cancelled = 0 AND reminder_sent = 0
                   AND starts_at > ? AND starts_at <= ? ORDER BY starts_at""",
            (now, now + lead),
        ).fetchall()
        return [self._row_to_event(r) for r in rows]

    def mark_reminded(self, message_id: int) -> None:
        with self.conn:
            self.conn.execute("UPDATE events SET reminder_sent = 1 WHERE message_id = ?", (message_id,))

    def events_needing_voice(self, now: int, lead: int, late: int) -> list[Event]:
        """Sorties qui commencent dans moins de `lead` secondes (ou ont commencé il y a moins de
        `late` secondes, pour rattraper un redémarrage) et n'ont pas encore de salon vocal."""
        rows = self.conn.execute(
            """SELECT * FROM events WHERE cancelled = 0 AND voice_channel_id IS NULL
                   AND starts_at > ? AND starts_at <= ? ORDER BY starts_at""",
            (now - late, now + lead),
        ).fetchall()
        return [self._row_to_event(r) for r in rows]

    def events_with_voice(self) -> list[Event]:
        rows = self.conn.execute("SELECT * FROM events WHERE voice_channel_id > 0").fetchall()
        return [self._row_to_event(r) for r in rows]

    def set_voice_channel(self, message_id: int, channel_id: int) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE events SET voice_channel_id = ? WHERE message_id = ?", (channel_id, message_id)
            )

    def delete_event(self, message_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM events WHERE message_id = ?", (message_id,))

    # ----------------------------------------------------------------- signups

    def get_signups(self, message_id: int) -> list[Signup]:
        rows = self.conn.execute(
            """SELECT s.user_id, s.role, s.signed_at, s.display_name, s.character_id,
                      c.name AS character_name, c.wow_class AS character_class
               FROM signups s LEFT JOIN characters c ON c.id = s.character_id
               WHERE s.message_id = ? ORDER BY s.signed_at""",
            (message_id,),
        ).fetchall()
        return [
            Signup(
                r["user_id"], r["role"], r["signed_at"], r["display_name"],
                r["character_id"], r["character_name"], r["character_class"],
            )
            for r in rows
            if r["role"] in ROLES
        ]

    def upsert_signup(
        self, message_id: int, user_id: int, role: str, display_name: str | None, character_id: int | None = None
    ) -> None:
        """Inscrit ou met à jour. Changer seulement de perso garde la place dans l'ordre d'inscription."""
        with self.conn:
            self.conn.execute(
                """INSERT INTO signups (message_id, user_id, role, signed_at, display_name, character_id)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT (message_id, user_id) DO UPDATE SET
                       signed_at = CASE WHEN role = excluded.role THEN signed_at ELSE excluded.signed_at END,
                       role = excluded.role,
                       display_name = excluded.display_name,
                       character_id = excluded.character_id""",
                (message_id, user_id, role, time.time(), display_name, character_id),
            )

    def delete_signup(self, message_id: int, user_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM signups WHERE message_id = ? AND user_id = ?", (message_id, user_id))

    # -------------------------------------------------------------- characters

    def _load_characters(self, rows: list[sqlite3.Row]) -> list[Character]:
        characters = [
            Character(
                r["id"], r["user_id"], r["name"], r["wow_class"], r["race"], r["preferred_role"],
                armory_synced_at=r["armory_synced_at"],
            )
            for r in rows
        ]
        if characters:
            by_id = {c.id: c for c in characters}
            marks = ",".join("?" * len(by_id))
            for p in self.conn.execute(
                f"SELECT * FROM character_professions WHERE character_id IN ({marks}) ORDER BY profession",
                tuple(by_id),
            ):
                by_id[p["character_id"]].professions[p["profession"]] = p["skill"]
        return characters

    def add_character(
        self, user_id: int, name: str, wow_class: str, race: str, preferred_role: str | None = None
    ) -> Character:
        """Lève sqlite3.IntegrityError si le joueur a déjà un perso de ce nom."""
        with self.conn:
            cur = self.conn.execute(
                """INSERT INTO characters (user_id, name, wow_class, race, preferred_role, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, name, wow_class, race, preferred_role, int(time.time())),
            )
        return Character(cur.lastrowid, user_id, name, wow_class, race, preferred_role)

    def get_characters(self, user_id: int) -> list[Character]:
        rows = self.conn.execute(
            "SELECT * FROM characters WHERE user_id = ? ORDER BY name COLLATE NOCASE", (user_id,)
        ).fetchall()
        return self._load_characters(rows)

    def get_character(self, character_id: int) -> Character | None:
        rows = self.conn.execute("SELECT * FROM characters WHERE id = ?", (character_id,)).fetchall()
        found = self._load_characters(rows)
        return found[0] if found else None

    def update_character(self, c: Character) -> None:
        """Enregistre nom, classe, race et rôle préféré. Lève sqlite3.IntegrityError si le nom est déjà pris."""
        with self.conn:
            self.conn.execute(
                "UPDATE characters SET name = ?, wow_class = ?, race = ?, preferred_role = ? WHERE id = ?",
                (c.name, c.wow_class, c.race, c.preferred_role, c.id),
            )

    def character_events(self, character_id: int) -> list[int]:
        """Sorties où ce perso est inscrit."""
        rows = self.conn.execute(
            "SELECT DISTINCT message_id FROM signups WHERE character_id = ?", (character_id,)
        ).fetchall()
        return [r["message_id"] for r in rows]

    def set_preferred_role(self, character_id: int, role: str | None) -> None:
        with self.conn:
            self.conn.execute("UPDATE characters SET preferred_role = ? WHERE id = ?", (role, character_id))

    def delete_character(self, user_id: int, character_id: int) -> list[int]:
        """Supprime le perso et renvoie les sorties où il était inscrit (pour mettre leur message à jour)."""
        with self.conn:
            rows = self.conn.execute(
                "SELECT DISTINCT message_id FROM signups WHERE character_id = ?", (character_id,)
            ).fetchall()
            self.conn.execute("DELETE FROM characters WHERE id = ? AND user_id = ?", (character_id, user_id))
        return [r["message_id"] for r in rows]

    # --------------------------------------------------------------- métiers

    def set_profession(self, character_id: int, profession: str, skill: int | None) -> None:
        with self.conn:
            self.conn.execute(
                """INSERT INTO character_professions (character_id, profession, skill) VALUES (?, ?, ?)
                   ON CONFLICT (character_id, profession) DO UPDATE SET skill = excluded.skill""",
                (character_id, profession, skill),
            )

    def remove_profession(self, character_id: int, profession: str) -> bool:
        with self.conn:
            cur = self.conn.execute(
                "DELETE FROM character_professions WHERE character_id = ? AND profession = ?",
                (character_id, profession),
            )
        return cur.rowcount > 0

    def characters_with_profession(self, guild_id: int, profession: str) -> list[tuple[Character, int | None]]:
        """Persos des membres du serveur qui ont ce métier, du plus haut niveau au plus bas."""
        rows = self.conn.execute(
            """SELECT c.*, p.skill FROM characters c
               JOIN character_professions p ON p.character_id = c.id
               JOIN guild_members m ON m.user_id = c.user_id AND m.guild_id = ?
               WHERE p.profession = ?
               ORDER BY p.skill IS NULL, p.skill DESC, c.name COLLATE NOCASE""",
            (guild_id, profession),
        ).fetchall()
        return [(c, r["skill"]) for c, r in zip(self._load_characters(rows), rows)]

    # ------------------------------------------------------- joueurs / serveurs

    def touch_member(self, guild_id: int, user_id: int) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO guild_members (guild_id, user_id) VALUES (?, ?)", (guild_id, user_id)
            )

    def set_battletag(self, user_id: int, battletag: str | None) -> None:
        with self.conn:
            self.conn.execute(
                """INSERT INTO players (user_id, battletag, updated_at) VALUES (?, ?, ?)
                   ON CONFLICT (user_id) DO UPDATE SET battletag = excluded.battletag,
                                                       updated_at = excluded.updated_at""",
                (user_id, battletag, int(time.time())),
            )

    def get_battletag(self, user_id: int) -> str | None:
        row = self.conn.execute("SELECT battletag FROM players WHERE user_id = ?", (user_id,)).fetchone()
        return row["battletag"] if row else None

    def battletags(self, guild_id: int) -> list[tuple[int, str]]:
        rows = self.conn.execute(
            """SELECT p.user_id, p.battletag FROM players p
               JOIN guild_members m ON m.user_id = p.user_id AND m.guild_id = ?
               WHERE p.battletag IS NOT NULL ORDER BY p.battletag COLLATE NOCASE""",
            (guild_id,),
        ).fetchall()
        return [(r["user_id"], r["battletag"]) for r in rows]

    # -------------------------------------------------------------- armurerie

    def replace_professions(self, character_id: int, skills: dict[str, int | None]) -> None:
        """Remplace tous les métiers du perso (ceux de l'armurerie font foi) et note la synchro."""
        with self.conn:
            self.conn.execute("DELETE FROM character_professions WHERE character_id = ?", (character_id,))
            self.conn.executemany(
                "INSERT INTO character_professions (character_id, profession, skill) VALUES (?, ?, ?)",
                [(character_id, p, s) for p, s in skills.items()],
            )
            self.conn.execute(
                "UPDATE characters SET armory_synced_at = ? WHERE id = ?", (int(time.time()), character_id)
            )

    def all_characters(self) -> list[Character]:
        return self._load_characters(self.conn.execute("SELECT * FROM characters ORDER BY id").fetchall())

    def characters_named(self, name: str) -> list[Character]:
        """Persos déclarés sous ce nom, tous joueurs confondus (insensible à la casse)."""
        rows = self.conn.execute(
            "SELECT * FROM characters WHERE name = ? COLLATE NOCASE ORDER BY id", (name.strip(),)
        ).fetchall()
        return self._load_characters(rows)

    def guild_characters(self, guild_id: int) -> list[Character]:
        rows = self.conn.execute(
            """SELECT c.* FROM characters c
               JOIN guild_members m ON m.user_id = c.user_id AND m.guild_id = ?
               ORDER BY c.name COLLATE NOCASE""",
            (guild_id,),
        ).fetchall()
        return self._load_characters(rows)

    # ---------------------------------------------------------------- recettes

    def replace_character_recipes(self, character_id: int, known: dict[str, list[tuple[int, str]]]) -> None:
        """Remplace les recettes connues du perso (armurerie) ; crée les recettes encore inconnues."""
        with self.conn:
            self.conn.executemany(
                "INSERT OR IGNORE INTO recipes (id, profession, name_en) VALUES (?, ?, ?)",
                [(rid, prof, name) for prof, items in known.items() for rid, name in items],
            )
            self.conn.execute("DELETE FROM character_recipes WHERE character_id = ?", (character_id,))
            self.conn.executemany(
                "INSERT OR IGNORE INTO character_recipes (character_id, recipe_id) VALUES (?, ?)",
                [(character_id, rid) for items in known.values() for rid, _ in items],
            )

    def recipes_missing_details(self, profession: str | None = None) -> list[int]:
        """Recettes dont le nom français et les composants n'ont pas encore été récupérés
        (ou l'ont été dans un ancien format)."""
        sql = "SELECT id FROM recipes WHERE (details_version IS NULL OR details_version < ?)"
        args: tuple = (RECIPE_DETAILS_VERSION,)
        if profession:
            sql += " AND profession = ?"
            args += (profession,)
        return [r["id"] for r in self.conn.execute(sql + " ORDER BY id", args)]

    def set_recipe_details(
        self,
        recipe_id: int,
        name: str,
        reagents: list[tuple[int, str, int | None]],
        crafted_item_id: int | None = None,
        crafted_quantity: float = 1.0,
    ) -> None:
        with self.conn:
            self.conn.execute(
                """UPDATE recipes SET name = ?, reagents = ?, crafted_item_id = ?, crafted_qty = ?,
                                      details_version = ?, fetched_at = ? WHERE id = ?""",
                (
                    name, json.dumps(reagents, ensure_ascii=False), crafted_item_id, crafted_quantity,
                    RECIPE_DETAILS_VERSION, int(time.time()), recipe_id,
                ),
            )

    def guild_recipes(self, guild_id: int, profession: str | None = None) -> list[GuildRecipe]:
        """Recettes (d'un métier, ou de tous) connues par au moins un perso d'un membre du serveur."""
        rows = self.conn.execute(
            """SELECT r.id, r.name, r.name_en, r.reagents, r.crafted_item_id, r.crafted_qty,
                      c.name AS character_name
               FROM recipes r
               JOIN character_recipes cr ON cr.recipe_id = r.id
               JOIN characters c ON c.id = cr.character_id
               JOIN guild_members m ON m.user_id = c.user_id AND m.guild_id = ?
               WHERE (? IS NULL OR r.profession = ?)
               ORDER BY c.name COLLATE NOCASE""",
            (guild_id, profession, profession),
        ).fetchall()
        by_id: dict[int, GuildRecipe] = {}
        for r in rows:
            recipe = by_id.get(r["id"])
            if recipe is None:
                reagents = None
                if r["reagents"]:
                    # Ancien format : (qté, nom) sans id d'objet.
                    reagents = [(x[0], x[1], x[2] if len(x) > 2 else None) for x in json.loads(r["reagents"])]
                recipe = by_id[r["id"]] = GuildRecipe(
                    r["id"], r["name"] or r["name_en"], reagents, [],
                    r["crafted_item_id"], r["crafted_qty"] or 1.0,
                )
            if r["character_name"] not in recipe.crafters:
                recipe.crafters.append(r["character_name"])
        return list(by_id.values())

    # ---------------------------------------------------------------- site web

    def character_recipe_ids(self, character_id: int) -> set[int]:
        rows = self.conn.execute("SELECT recipe_id FROM character_recipes WHERE character_id = ?", (character_id,))
        return {r["recipe_id"] for r in rows}

    def known_guild_ids(self) -> list[int]:
        return [r["guild_id"] for r in self.conn.execute("SELECT DISTINCT guild_id FROM guild_members ORDER BY guild_id")]

    def recipe_crafters(self, guild_id: int) -> dict[int, list[Crafter]]:
        """recette -> persos des membres du serveur qui la connaissent (triés par nom)."""
        rows = self.conn.execute(
            """SELECT cr.recipe_id, c.id, c.name, c.user_id, c.wow_class
               FROM character_recipes cr
               JOIN characters c ON c.id = cr.character_id
               JOIN guild_members m ON m.user_id = c.user_id AND m.guild_id = ?
               ORDER BY c.name COLLATE NOCASE""",
            (guild_id,),
        )
        result: dict[int, list[Crafter]] = {}
        for r in rows:
            result.setdefault(r["recipe_id"], []).append(Crafter(r["id"], r["name"], r["user_id"], r["wow_class"]))
        return result

    # ---------------------------------------------------------------- commandes

    _ORDER_COLUMNS = (
        "guild_id", "requester_id", "requester_name", "recipe_id", "recipe_name", "quantity", "reagents_text",
        "note", "crafter_character_id", "crafter_name", "crafter_user_id", "status", "created_at", "updated_at",
        "crafter_dm_channel_id", "crafter_dm_message_id",
    )

    def create_order(self, order: Order) -> Order:
        with self.conn:
            cur = self.conn.execute(
                f"INSERT INTO orders ({', '.join(self._ORDER_COLUMNS)}) "
                f"VALUES ({', '.join('?' * len(self._ORDER_COLUMNS))})",
                tuple(getattr(order, c) for c in self._ORDER_COLUMNS),
            )
        order.id = cur.lastrowid
        return order

    def _row_to_order(self, row: sqlite3.Row) -> Order:
        return Order(**{c: row[c] for c in self._ORDER_COLUMNS}, id=row["id"])

    def get_order(self, order_id: int) -> Order | None:
        row = self.conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        return self._row_to_order(row) if row else None

    def set_order_status(self, order_id: int, status: str, expected: tuple[str, ...]) -> bool:
        """Change l'état seulement s'il est encore dans `expected` (deux clics simultanés : un seul gagne)."""
        with self.conn:
            cur = self.conn.execute(
                f"UPDATE orders SET status = ?, updated_at = ? WHERE id = ? AND status IN ({','.join('?' * len(expected))})",
                (status, int(time.time()), order_id, *expected),
            )
        return cur.rowcount == 1

    def set_order_dm(self, order_id: int, channel_id: int, message_id: int) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE orders SET crafter_dm_channel_id = ?, crafter_dm_message_id = ? WHERE id = ?",
                (channel_id, message_id, order_id),
            )

    def user_orders(self, user_id: int, closed_limit: int = 5) -> list[Order]:
        """Commandes passées ou reçues : toutes celles en cours, puis les dernières terminées."""
        base = "SELECT * FROM orders WHERE (requester_id = ? OR crafter_user_id = ?)"
        active = self.conn.execute(
            base + " AND status IN ('pending', 'accepted') ORDER BY created_at, id", (user_id, user_id)
        ).fetchall()
        closed = self.conn.execute(
            base + " AND status NOT IN ('pending', 'accepted') ORDER BY updated_at DESC, id DESC LIMIT ?",
            (user_id, user_id, closed_limit),
        ).fetchall()
        return [self._row_to_order(r) for r in [*active, *closed]]
