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

-- Icônes des objets (hébergées par Blizzard), une seule demande par objet. url NULL : pas d'icône.
CREATE TABLE IF NOT EXISTS item_icons (
    item_id INTEGER PRIMARY KEY,
    url     TEXT
);

-- Priorités de stats relues chaque nuit dans le guide (clé : spé, ou « hit_caps »), voir statsource.
CREATE TABLE IF NOT EXISTS stat_priorities (
    key        TEXT    PRIMARY KEY,
    value      TEXT    NOT NULL,
    updated_at INTEGER NOT NULL
);

-- Arbres de talents de Forever (données de jeu, pas de perso), redemandés de temps en temps.
CREATE TABLE IF NOT EXISTS talent_trees (
    spec_id    INTEGER PRIMARY KEY,
    class      TEXT,
    position   INTEGER NOT NULL,
    data       TEXT    NOT NULL,
    fetched_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_crafter ON orders (crafter_user_id);

-- Hôtel des ventes (voir auctions.py) : base locale des objets de Forever (recherche d'objets de l'API).
CREATE TABLE IF NOT EXISTS ah_items (
    id             INTEGER PRIMARY KEY,
    name           TEXT    NOT NULL,
    search         TEXT    NOT NULL,
    quality        TEXT,
    class_id       INTEGER,
    class_name     TEXT,
    subclass_id    INTEGER,
    subclass_name  TEXT,
    level          INTEGER,
    required_level INTEGER,
    sell_price     INTEGER,
    stackable      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_ah_items_class ON ah_items (class_id, subclass_id);
-- Dernier relevé de chaque objet en vente (gardé si l'API ne répond plus : le site montre alors ces prix-là).
CREATE TABLE IF NOT EXISTS ah_latest (
    item_id      INTEGER PRIMARY KEY,
    ts           INTEGER NOT NULL,
    min_price    INTEGER NOT NULL,
    median_price INTEGER NOT NULL,
    quantity     INTEGER NOT NULL,
    listings     INTEGER NOT NULL
);
-- Historique des prix : un relevé par heure pendant 7 jours, puis un par jour (ts à minuit UTC).
CREATE TABLE IF NOT EXISTS ah_prices (
    item_id      INTEGER NOT NULL,
    ts           INTEGER NOT NULL,
    min_price    INTEGER NOT NULL,
    median_price INTEGER NOT NULL,
    quantity     INTEGER NOT NULL,
    listings     INTEGER NOT NULL,
    PRIMARY KEY (item_id, ts)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS ah_favorites (
    user_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    PRIMARY KEY (user_id, item_id)
);
-- Ventes estimées (voir auctions.estimate_sales) : quantité vendue par objet et par heure (7 jours), puis par jour.
-- ah_sales_cover : heures où l'estimation a pu se faire (hours = 1 par heure, nombre d'heures couvertes par jour) ;
-- un objet sans ligne pour une heure couverte n'a rien vendu.
CREATE TABLE IF NOT EXISTS ah_sales (
    item_id INTEGER NOT NULL,
    ts      INTEGER NOT NULL,
    sold    INTEGER NOT NULL,
    PRIMARY KEY (item_id, ts)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS ah_sales_cover (
    ts    INTEGER PRIMARY KEY,
    hours INTEGER NOT NULL
);
-- Petits réglages persistants (date des dernières données de l'hôtel des ventes…).
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
-- Addon WoW : jeton personnel du client local (seule son empreinte SHA-256 est gardée), un par joueur.
CREATE TABLE IF NOT EXISTS addon_tokens (
    user_id      INTEGER PRIMARY KEY,
    token_hash   TEXT    NOT NULL UNIQUE,
    created_at   INTEGER NOT NULL,
    last_used_at INTEGER,
    checked_at   INTEGER  -- dernière vérification que le joueur est toujours membre du serveur
);
-- Addon WoW : sacs et banque vus en jeu (la banque n'est relevée qu'à son ouverture).
CREATE TABLE IF NOT EXISTS game_inventory (
    character_id INTEGER PRIMARY KEY REFERENCES characters (id) ON DELETE CASCADE,
    updated_at   INTEGER NOT NULL,  -- dernier relevé des sacs en jeu
    bank_at      INTEGER,           -- dernière ouverture de la banque (NULL : jamais vue)
    money        INTEGER
);
CREATE TABLE IF NOT EXISTS game_items (
    character_id INTEGER NOT NULL REFERENCES characters (id) ON DELETE CASCADE,
    item_id      INTEGER NOT NULL,
    bags         INTEGER NOT NULL DEFAULT 0,
    bank         INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (character_id, item_id)
) WITHOUT ROWID;
-- Addon WoW : recettes vues dans la fenêtre de métier en jeu (gardées quand l'armurerie remplace les siennes).
CREATE TABLE IF NOT EXISTS game_recipes (
    character_id INTEGER NOT NULL REFERENCES characters (id) ON DELETE CASCADE,
    recipe_id    INTEGER NOT NULL REFERENCES recipes (id),
    PRIMARY KEY (character_id, recipe_id)
) WITHOUT ROWID;
-- Droits du site confiés par un admin du serveur (« Gérer le serveur ») à un membre : rights = "persos,sorties".
CREATE TABLE IF NOT EXISTS site_delegations (
    guild_id   INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    rights     TEXT    NOT NULL,
    granted_by INTEGER NOT NULL,
    granted_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id)
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
    reminder_sent: bool = False
    # None : pas encore créé · 0 : supprimé ou création impossible · >0 : ID du salon vocal
    voice_channel_id: int | None = None
    # Pseudo de l'organisateur (pour le site, qui n'affiche pas les mentions Discord).
    creator_name: str | None = None

    @property
    def size(self) -> int:
        return sum(self.caps.values())


@dataclass(frozen=True)
class Delegation:
    """Droits du site confiés à un membre par un admin du serveur."""
    user_id: int
    rights: frozenset[str]
    granted_by: int
    granted_at: int


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
    # Lus dans l'armurerie : niveau, portrait et rendu en pied (images hébergées par Blizzard).
    level: int | None = None
    avatar_url: str | None = None
    render_url: str | None = None
    # Talents choisis, voir ArmorySheet.talents.
    talents: list | None = None
    # Caractéristiques et objets portés, voir gear.parse_stats / gear.parse_equipment.
    stats: dict | None = None
    equipment: list | None = None
    # Où le perso a été déclaré : « web » (vérifié dans l'armurerie à l'ajout), sinon Discord.
    source: str | None = None
    created_at: int | None = None
    # Perso préféré du joueur (un seul) : proposé en premier pour s'inscrire.
    favorite: bool = False


# Persos ajoutés depuis le site (les autres viennent de Discord).
SOURCE_WEB = "web"


# Version du format des détails de recette ; une recette plus ancienne est redemandée à Blizzard.
# 2 : identifiants des composants et de l'objet fabriqué (pour relier les sous-recettes).
# 3 : effet de la recette et infobulle de l'objet fabriqué (stats, effets), pour le site.
# 4 : type de l'objet fabriqué (composant d'artisanat, consommable, armure…), pour classer les recettes.
# 5 : sous-type exact, niveau requis et niveau d'objet, pour l'équipement conseillé sur la fiche perso.
RECIPE_DETAILS_VERSION = 5


@dataclass
class GuildRecipe:
    id: int
    name: str
    reagents: list[tuple[int, str, int | None]] | None  # (qté, nom, id objet) ; None : pas encore récupérés
    crafters: list[str]  # noms des persos qui la connaissent
    crafted_item_id: int | None = None
    crafted_quantity: float = 1.0
    description: str | None = None  # effet de la recette (enchantements)
    item: dict | None = None  # infobulle de l'objet fabriqué, voir armory.parse_item


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
        # v1.13 → v1.14 : sorties créées depuis le site.
        if "creator_name" not in columns:
            self.conn.execute("ALTER TABLE events ADD COLUMN creator_name TEXT")
        # v1.3 → v1.4 : synchro des métiers depuis l'armurerie.
        columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(characters)")}
        if "armory_synced_at" not in columns:
            self.conn.execute("ALTER TABLE characters ADD COLUMN armory_synced_at INTEGER")
        # v1.5 → v1.6 : niveau et images du perso.
        for column in (
            "level INTEGER", "avatar_url TEXT", "render_url TEXT", "talents TEXT", "stats TEXT", "equipment TEXT",
            "source TEXT",  # v1.13 → v1.14 : persos ajoutés depuis le site
            "favorite INTEGER NOT NULL DEFAULT 0",  # v1.14 → v1.15 : perso préféré
        ):
            if column.split()[0] not in columns:
                self.conn.execute(f"ALTER TABLE characters ADD COLUMN {column}")
        # v1.4 → v1.5 : liens entre recettes (composant fabriqué par une autre recette).
        columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(recipes)")}
        for column in (
            "crafted_item_id INTEGER", "crafted_qty REAL", "details_version INTEGER",
            "description TEXT", "item_info TEXT",  # v1.5 → v1.6 : ce que fait l'objet
        ):
            if column.split()[0] not in columns:
                self.conn.execute(f"ALTER TABLE recipes ADD COLUMN {column}")
        # v1.17 → v1.18 : prix d'achat chez les marchands (page Rentabilité).
        columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(ah_items)")}
        for column in ("purchase_price INTEGER", "purchase_quantity INTEGER NOT NULL DEFAULT 1"):
            if column.split()[0] not in columns:
                self.conn.execute(f"ALTER TABLE ah_items ADD COLUMN {column}")
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
            creator_name=row["creator_name"],
        )

    def create_event(self, ev: Event) -> None:
        with self.conn:
            self.conn.execute(
                """INSERT INTO events (message_id, guild_id, channel_id, creator_id, instance, kind, levels,
                                       starts_at, tank_cap, heal_cap, dps_cap, description, cancelled, created_at,
                                       creator_name)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ev.message_id, ev.guild_id, ev.channel_id, ev.creator_id, ev.instance, ev.kind, ev.levels,
                    ev.starts_at, ev.caps["tank"], ev.caps["heal"], ev.caps["dps"], ev.description,
                    int(ev.cancelled), ev.created_at, ev.creator_name,
                ),
            )

    def last_event_channel(self, guild_id: int) -> int | None:
        """Salon de la dernière sortie créée sur le serveur (pour le site, sans EVENT_CHANNEL_IDS)."""
        row = self.conn.execute(
            "SELECT channel_id FROM events WHERE guild_id = ? ORDER BY created_at DESC LIMIT 1", (guild_id,)
        ).fetchone()
        return row["channel_id"] if row else None

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
                level=r["level"], avatar_url=r["avatar_url"], render_url=r["render_url"],
                talents=json.loads(r["talents"]) if r["talents"] else None,
                stats=json.loads(r["stats"]) if r["stats"] else None,
                equipment=json.loads(r["equipment"]) if r["equipment"] else None,
                source=r["source"], created_at=r["created_at"], favorite=bool(r["favorite"]),
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
        self, user_id: int, name: str, wow_class: str, race: str, preferred_role: str | None = None,
        source: str | None = None,
    ) -> Character:
        """Lève sqlite3.IntegrityError si le joueur a déjà un perso de ce nom."""
        now = int(time.time())
        with self.conn:
            cur = self.conn.execute(
                """INSERT INTO characters (user_id, name, wow_class, race, preferred_role, created_at, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (user_id, name, wow_class, race, preferred_role, now, source),
            )
        return Character(cur.lastrowid, user_id, name, wow_class, race, preferred_role, source=source, created_at=now)

    def set_preferred_role(self, character_id: int, role: str | None) -> None:
        with self.conn:
            self.conn.execute("UPDATE characters SET preferred_role = ? WHERE id = ?", (role, character_id))

    def set_favorite(self, user_id: int, character_id: int | None) -> None:
        """Perso préféré du joueur (un seul) ; None : plus aucun."""
        with self.conn:
            self.conn.execute("UPDATE characters SET favorite = 0 WHERE user_id = ?", (user_id,))
            if character_id is not None:
                self.conn.execute(
                    "UPDATE characters SET favorite = 1 WHERE id = ? AND user_id = ?", (character_id, user_id)
                )

    def last_display_name(self, user_id: int) -> str | None:
        """Dernier pseudo connu du joueur (vu à son inscription à une sortie)."""
        row = self.conn.execute(
            """SELECT display_name FROM signups WHERE user_id = ? AND display_name IS NOT NULL
               ORDER BY signed_at DESC LIMIT 1""",
            (user_id,),
        ).fetchone()
        return row["display_name"] if row else None

    def guild_member_ids(self, guild_id: int) -> list[int]:
        return [r["user_id"] for r in self.conn.execute(
            "SELECT user_id FROM guild_members WHERE guild_id = ? ORDER BY user_id", (guild_id,)
        )]

    def get_characters(self, user_id: int) -> list[Character]:
        rows = self.conn.execute(
            "SELECT * FROM characters WHERE user_id = ? ORDER BY name COLLATE NOCASE", (user_id,)
        ).fetchall()
        return self._load_characters(rows)

    def get_character(self, character_id: int) -> Character | None:
        rows = self.conn.execute("SELECT * FROM characters WHERE id = ?", (character_id,)).fetchall()
        found = self._load_characters(rows)
        return found[0] if found else None

    def delete_character(self, user_id: int, character_id: int) -> list[int]:
        """Supprime le perso et renvoie les sorties où il était inscrit (pour mettre leur message à jour)."""
        with self.conn:
            rows = self.conn.execute(
                "SELECT DISTINCT message_id FROM signups WHERE character_id = ?", (character_id,)
            ).fetchall()
            self.conn.execute("DELETE FROM characters WHERE id = ? AND user_id = ?", (character_id, user_id))
        return [r["message_id"] for r in rows]

    # --------------------------------------------------------------- métiers

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

    def set_armory_look(
        self, character_id: int, level: int | None, avatar_url: str | None, render_url: str | None,
        talents: list | None = None,
        stats: dict | None = None,
        equipment: list | None = None,
    ) -> None:
        """Niveau, images, talents, stats et équipement lus dans l'armurerie (on garde l'ancien si l'armurerie
        n'en donne pas)."""
        dump = lambda v: json.dumps(v, ensure_ascii=False) if v is not None else None  # noqa: E731
        with self.conn:
            self.conn.execute(
                """UPDATE characters SET level = COALESCE(?, level), avatar_url = COALESCE(?, avatar_url),
                                         render_url = COALESCE(?, render_url), talents = COALESCE(?, talents),
                                         stats = COALESCE(?, stats), equipment = COALESCE(?, equipment)
                   WHERE id = ?""",
                (level, avatar_url, render_url, dump(talents), dump(stats), dump(equipment), character_id),
            )

    # ------------------------------------------------------------ item icons

    def item_icons(self, item_ids: set[int] | list[int]) -> dict[int, str]:
        ids = [i for i in item_ids if isinstance(i, int)]
        if not ids:
            return {}
        rows = self.conn.execute(
            f"SELECT item_id, url FROM item_icons WHERE item_id IN ({','.join('?' * len(ids))})", ids
        ).fetchall()
        return {r["item_id"]: r["url"] for r in rows if r["url"]}

    def set_item_icons(self, icons: dict[int, str | None]) -> None:
        with self.conn:
            self.conn.executemany(
                "INSERT OR REPLACE INTO item_icons (item_id, url) VALUES (?, ?)", list(icons.items())
            )

    # ------------------------------------------------------------ stat priorities

    def set_stat_priorities(self, specs: dict[str, list[str]], caps: dict[str, float]) -> None:
        now = int(time.time())
        rows = [(spec, json.dumps(tokens), now) for spec, tokens in specs.items()]
        if caps:
            rows.append(("hit_caps", json.dumps(caps), now))
        with self.conn:
            self.conn.executemany(
                "INSERT OR REPLACE INTO stat_priorities (key, value, updated_at) VALUES (?, ?, ?)", rows
            )

    def stat_priorities(self) -> tuple[dict[str, list[str]], dict[str, float], int | None]:
        """(priorités par spé, caps de toucher, date de la dernière lecture réussie du guide)."""
        specs: dict[str, list[str]] = {}
        caps: dict[str, float] = {}
        last = None
        for r in self.conn.execute("SELECT key, value, updated_at FROM stat_priorities"):
            if r["key"] == "hit_caps":
                caps = json.loads(r["value"])
            else:
                specs[r["key"]] = json.loads(r["value"])
            last = max(last or 0, r["updated_at"])
        return specs, caps, last

    # ------------------------------------------------------------ talent trees

    def replace_talent_trees(self, trees: list[dict]) -> None:
        """Remplace tous les arbres (dans l'ordre du jeu), voir armory.parse_talent_tree."""
        now = int(time.time())
        with self.conn:
            self.conn.execute("DELETE FROM talent_trees")
            self.conn.executemany(
                "INSERT OR REPLACE INTO talent_trees (spec_id, class, position, data, fetched_at) VALUES (?, ?, ?, ?, ?)",
                [(t["spec_id"], t["class"], i, json.dumps(t, ensure_ascii=False), now) for i, t in enumerate(trees)],
            )

    def talent_trees(self, wow_class: str | None = None) -> list[dict]:
        rows = self.conn.execute(
            "SELECT data FROM talent_trees" + (" WHERE class = ?" if wow_class else "") + " ORDER BY position",
            (wow_class,) if wow_class else (),
        ).fetchall()
        return [json.loads(r["data"]) for r in rows]

    def talent_trees_age(self) -> float | None:
        """Secondes depuis la dernière récupération des arbres, None s'il n'y en a pas."""
        row = self.conn.execute("SELECT MIN(fetched_at) AS t FROM talent_trees").fetchone()
        return time.time() - row["t"] if row and row["t"] else None

    def all_characters(self) -> list[Character]:
        return self._load_characters(self.conn.execute("SELECT * FROM characters ORDER BY id").fetchall())

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
            # Les recettes vues en jeu (addon) restent : l'armurerie n'en montre qu'une partie.
            self.conn.execute(
                """INSERT OR IGNORE INTO character_recipes (character_id, recipe_id)
                   SELECT character_id, recipe_id FROM game_recipes WHERE character_id = ?""",
                (character_id,),
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

    def all_recipe_ids(self) -> list[int]:
        """Toutes les recettes connues (pour /admin sync, qui redemande tous les détails)."""
        return [r["id"] for r in self.conn.execute("SELECT id FROM recipes ORDER BY id")]

    def set_recipe_details(
        self,
        recipe_id: int,
        name: str,
        reagents: list[tuple[int, str, int | None]],
        crafted_item_id: int | None = None,
        crafted_quantity: float = 1.0,
        description: str | None = None,
        item_info: dict | None = None,
    ) -> None:
        with self.conn:
            self.conn.execute(
                """UPDATE recipes SET name = ?, reagents = ?, crafted_item_id = ?, crafted_qty = ?, description = ?,
                                      item_info = ?, details_version = ?, fetched_at = ? WHERE id = ?""",
                (
                    name, json.dumps(reagents, ensure_ascii=False), crafted_item_id, crafted_quantity, description,
                    json.dumps(item_info, ensure_ascii=False) if item_info else None,
                    RECIPE_DETAILS_VERSION, int(time.time()), recipe_id,
                ),
            )

    def guild_recipes(self, guild_id: int, profession: str | None = None) -> list[GuildRecipe]:
        """Recettes (d'un métier, ou de tous) connues par au moins un perso d'un membre du serveur."""
        rows = self.conn.execute(
            """SELECT r.id, r.name, r.name_en, r.reagents, r.crafted_item_id, r.crafted_qty,
                      r.description, r.item_info, c.name AS character_name
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
                    r["description"], json.loads(r["item_info"]) if r["item_info"] else None,
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

    # --------------------------------------------------------------- réglages

    def get_setting(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))

    # ---------------------------------------------------------- hôtel des ventes

    def upsert_ah_items(self, items: list) -> None:
        """Objets de la base locale (auctions.ItemRecord), remplacés s'ils existent déjà."""
        with self.conn:
            self.conn.executemany(
                """INSERT OR REPLACE INTO ah_items (id, name, search, quality, class_id, class_name, subclass_id,
                                                  subclass_name, level, required_level, sell_price, stackable,
                                                  purchase_price, purchase_quantity)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (i.id, i.name, i.search, i.quality, i.class_id, i.class_name, i.subclass_id, i.subclass_name,
                     i.level, i.required_level, i.sell_price, int(i.stackable), i.purchase_price, i.purchase_quantity)
                    for i in items
                ],
            )

    def ah_items_map(self, item_ids: set[int] | list[int]) -> dict[int, sqlite3.Row]:
        """Objets du catalogue (nom, qualité, prix marchands, icône) avec leur dernier prix à l'HdV s'il est en
        vente (min_price, median_price, quantity, listings ; NULL sinon)."""
        ids = sorted({i for i in item_ids if isinstance(i, int)})
        result: dict[int, sqlite3.Row] = {}
        for start in range(0, len(ids), 500):  # limite de paramètres de SQLite
            chunk = ids[start:start + 500]
            rows = self.conn.execute(
                f"""SELECT i.*, l.min_price, l.median_price, l.quantity, l.listings, ic.url AS icon
                    FROM ah_items i LEFT JOIN ah_latest l ON l.item_id = i.id
                    LEFT JOIN item_icons ic ON ic.item_id = i.id
                    WHERE i.id IN ({','.join('?' * len(chunk))})""",
                chunk,
            )
            result.update({r["id"]: r for r in rows})
        return result

    def ah_tradeskill_on_sale(self, subclass_id: int) -> list[sqlite3.Row]:
        """Matières premières (artisanat, ce sous-type) en vente à l'HdV, avec prix marchand de revente."""
        return self.conn.execute(
            """SELECT l.*, i.name, i.quality, i.sell_price, ic.url AS icon
               FROM ah_latest l JOIN ah_items i ON i.id = l.item_id
               LEFT JOIN item_icons ic ON ic.item_id = l.item_id
               WHERE i.class_id = 7 AND i.subclass_id = ? ORDER BY l.min_price DESC""",
            (subclass_id,),
        ).fetchall()

    def ah_item_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM ah_items").fetchone()[0]

    def ah_unknown_items(self, limit: int) -> list[int]:
        """Objets en vente absents de la base locale (nouveaux objets, à demander un par un)."""
        rows = self.conn.execute(
            """SELECT l.item_id FROM ah_latest l LEFT JOIN ah_items i ON i.id = l.item_id
               WHERE i.id IS NULL ORDER BY l.item_id LIMIT ?""",
            (limit,),
        )
        return [r[0] for r in rows]

    def ah_missing_icons(self, limit: int) -> list[int]:
        rows = self.conn.execute(
            """SELECT l.item_id FROM ah_latest l LEFT JOIN item_icons ic ON ic.item_id = l.item_id
               WHERE ic.item_id IS NULL ORDER BY l.listings DESC LIMIT ?""",
            (limit,),
        )
        return [r[0] for r in rows]

    def store_ah_snapshot(self, ts: int, points: dict) -> None:
        """Relevé complet (objet → auctions.PricePoint) : historique, et remplace la liste des objets en vente."""
        rows = [(item_id, ts, p.min_price, p.median_price, p.quantity, p.listings) for item_id, p in points.items()]
        with self.conn:
            self.conn.executemany(
                """INSERT OR REPLACE INTO ah_prices (item_id, ts, min_price, median_price, quantity, listings)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                rows,
            )
            self.conn.execute("DELETE FROM ah_latest")
            self.conn.executemany(
                """INSERT INTO ah_latest (item_id, ts, min_price, median_price, quantity, listings)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                rows,
            )

    def compact_ah_prices(self, now: int, hourly_days: int = 7, keep_days: int = 90) -> None:
        """Au-delà de `hourly_days`, un relevé par jour (plus bas prix du jour, moyennes du reste) ; au-delà de
        `keep_days`, plus rien."""
        cutoff = (now - hourly_days * 86400) // 86400 * 86400
        with self.conn:
            self.conn.execute(
                """INSERT OR REPLACE INTO ah_prices (item_id, ts, min_price, median_price, quantity, listings)
                   SELECT item_id, ts / 86400 * 86400, MIN(min_price), CAST(AVG(median_price) AS INTEGER),
                          CAST(AVG(quantity) AS INTEGER), CAST(AVG(listings) AS INTEGER)
                   FROM ah_prices WHERE ts < ? AND ts % 86400 != 0 GROUP BY item_id, ts / 86400""",
                (cutoff,),
            )
            self.conn.execute("DELETE FROM ah_prices WHERE ts < ? AND ts % 86400 != 0", (cutoff,))
            self.conn.execute("DELETE FROM ah_prices WHERE ts < ?", (now - keep_days * 86400,))

    def store_ah_sales(self, ts: int, sold: dict[int, int]) -> None:
        """Ventes estimées sur l'heure `ts` (plusieurs relevés dans la même heure s'additionnent)."""
        with self.conn:
            self.conn.executemany(
                """INSERT INTO ah_sales (item_id, ts, sold) VALUES (?, ?, ?)
                   ON CONFLICT (item_id, ts) DO UPDATE SET sold = sold + excluded.sold""",
                [(item_id, ts, n) for item_id, n in sold.items() if n > 0],
            )
            self.conn.execute("INSERT OR IGNORE INTO ah_sales_cover (ts, hours) VALUES (?, 1)", (ts,))

    def compact_ah_sales(self, now: int, hourly_days: int = 7, keep_days: int = 90) -> None:
        """Au-delà de `hourly_days`, une ligne par jour (somme des heures) ; au-delà de `keep_days`, plus rien."""
        cutoff = (now - hourly_days * 86400) // 86400 * 86400
        days = [r[0] for r in self.conn.execute(
            "SELECT DISTINCT ts / 86400 * 86400 FROM ah_sales_cover WHERE ts < ? AND ts % 86400 != 0", (cutoff,)
        )]
        with self.conn:
            for day in days:
                span = (day, day + 86400)
                self.conn.execute(
                    """INSERT OR REPLACE INTO ah_sales (item_id, ts, sold)
                       SELECT item_id, ?, SUM(sold) FROM ah_sales WHERE ts >= ? AND ts < ? GROUP BY item_id""",
                    (day, *span),
                )
                self.conn.execute(
                    """INSERT OR REPLACE INTO ah_sales_cover (ts, hours)
                       SELECT ?, SUM(hours) FROM ah_sales_cover WHERE ts >= ? AND ts < ?""",
                    (day, *span),
                )
                self.conn.execute("DELETE FROM ah_sales WHERE ts > ? AND ts < ?", span)
                self.conn.execute("DELETE FROM ah_sales_cover WHERE ts > ? AND ts < ?", span)
            self.conn.execute("DELETE FROM ah_sales WHERE ts < ?", (now - keep_days * 86400,))
            self.conn.execute("DELETE FROM ah_sales_cover WHERE ts < ?", (now - keep_days * 86400,))

    def ah_sales_history(self, item_id: int, since: int) -> list[tuple[int, int, int]]:
        """[(ts, quantité vendue, heures couvertes)] depuis `since` : une ligne par heure (ou par jour au-delà de 7
        jours) où l'estimation a pu se faire, 0 si rien ne s'est vendu."""
        rows = self.conn.execute(
            """SELECT c.ts, COALESCE(s.sold, 0), c.hours FROM ah_sales_cover c
               LEFT JOIN ah_sales s ON s.item_id = ? AND s.ts = c.ts WHERE c.ts >= ? ORDER BY c.ts""",
            (item_id, since),
        )
        return [tuple(r) for r in rows]

    # ---------------------------------------------------- droits délégués (site)

    def delegations(self, guild_id: int) -> list[Delegation]:
        rows = self.conn.execute(
            "SELECT * FROM site_delegations WHERE guild_id = ? ORDER BY granted_at", (guild_id,)
        )
        return [
            Delegation(r["user_id"], frozenset(filter(None, r["rights"].split(","))), r["granted_by"], r["granted_at"])
            for r in rows
        ]

    def delegation_rights(self, guild_id: int, user_id: int) -> frozenset[str]:
        row = self.conn.execute(
            "SELECT rights FROM site_delegations WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        ).fetchone()
        return frozenset(filter(None, row["rights"].split(","))) if row else frozenset()

    def set_delegation(self, guild_id: int, user_id: int, rights: set[str] | frozenset[str], granted_by: int,
                       now: int) -> None:
        """Droits confiés au membre (aucun : la délégation est retirée)."""
        with self.conn:
            if not rights:
                self.conn.execute("DELETE FROM site_delegations WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
                return
            self.conn.execute(
                "INSERT OR REPLACE INTO site_delegations (guild_id, user_id, rights, granted_by, granted_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (guild_id, user_id, ",".join(sorted(rights)), granted_by, now),
            )

    # ------------------------------------------------------------ addon WoW

    def set_addon_token(self, user_id: int, token_hash: str, now: int) -> None:
        """Nouveau jeton du joueur (l'ancien ne marche plus)."""
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO addon_tokens (user_id, token_hash, created_at, checked_at) VALUES (?, ?, ?, ?)",
                (user_id, token_hash, now, now),
            )

    def delete_addon_token(self, user_id: int) -> bool:
        with self.conn:
            return self.conn.execute("DELETE FROM addon_tokens WHERE user_id = ?", (user_id,)).rowcount > 0

    def addon_token(self, user_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM addon_tokens WHERE user_id = ?", (user_id,)).fetchone()

    def addon_token_owner(self, token_hash: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM addon_tokens WHERE token_hash = ?", (token_hash,)).fetchone()

    def touch_addon_token(self, user_id: int, now: int, checked: bool = False) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE addon_tokens SET last_used_at = ?, checked_at = CASE WHEN ? THEN ? ELSE checked_at END "
                "WHERE user_id = ?",
                (now, int(checked), now, user_id),
            )

    def addon_prices(self, now: int) -> list[tuple[int, int, int, int]]:
        """[(objet, prix le plus bas, prix médian, ventes estimées sur 24 h)] du dernier relevé de l'HdV."""
        rows = self.conn.execute(
            """SELECT l.item_id, l.min_price, l.median_price, COALESCE(s.sold, 0) FROM ah_latest l
               LEFT JOIN (SELECT item_id, SUM(sold) AS sold FROM ah_sales WHERE ts >= ? GROUP BY item_id) s
                 ON s.item_id = l.item_id
               ORDER BY l.item_id""",
            (now - 86400,),
        )
        return [tuple(r) for r in rows]

    def recipes_of_profession(self, profession: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT id, name, name_en, crafted_item_id FROM recipes WHERE profession = ?", (profession,)
        ).fetchall()

    def store_game_character(
        self, character_id: int, *, level: int | None, money: int | None, updated_at: int,
        bags: dict[int, int], bank: dict[int, int] | None, bank_at: int | None,
        professions: dict[str, int | None] | None, recipe_ids: set[int] | None,
    ) -> None:
        """Ce que l'addon a vu en jeu pour un perso : niveau, argent, sacs, banque (None : jamais ouverte, on garde
        l'ancienne), métiers (None : inconnus) et recettes reconnues (None : fenêtre de métier jamais ouverte)."""
        with self.conn:
            if level:
                self.conn.execute("UPDATE characters SET level = ? WHERE id = ?", (level, character_id))
            old = self.conn.execute(
                "SELECT bank_at FROM game_inventory WHERE character_id = ?", (character_id,)
            ).fetchone()
            keep_bank = bank is None
            if keep_bank:
                bank_at = old["bank_at"] if old else None
                bank = {
                    r["item_id"]: r["bank"] for r in self.conn.execute(
                        "SELECT item_id, bank FROM game_items WHERE character_id = ? AND bank > 0", (character_id,)
                    )
                }
            self.conn.execute(
                "INSERT OR REPLACE INTO game_inventory (character_id, updated_at, bank_at, money) VALUES (?, ?, ?, ?)",
                (character_id, updated_at, bank_at, money),
            )
            self.conn.execute("DELETE FROM game_items WHERE character_id = ?", (character_id,))
            self.conn.executemany(
                "INSERT INTO game_items (character_id, item_id, bags, bank) VALUES (?, ?, ?, ?)",
                [(character_id, i, bags.get(i, 0), bank.get(i, 0)) for i in set(bags) | set(bank)],
            )
            if professions is not None:
                self.conn.execute("DELETE FROM character_professions WHERE character_id = ?", (character_id,))
                self.conn.executemany(
                    "INSERT INTO character_professions (character_id, profession, skill) VALUES (?, ?, ?)",
                    [(character_id, p, s) for p, s in professions.items()],
                )
            if recipe_ids is not None:
                self.conn.execute("DELETE FROM game_recipes WHERE character_id = ?", (character_id,))
                rows = [(character_id, rid) for rid in recipe_ids]
                self.conn.executemany("INSERT INTO game_recipes (character_id, recipe_id) VALUES (?, ?)", rows)
                self.conn.executemany(
                    "INSERT OR IGNORE INTO character_recipes (character_id, recipe_id) VALUES (?, ?)", rows
                )

    def game_inventory(self, character_id: int) -> tuple[sqlite3.Row | None, dict[int, int]]:
        """(relevé : updated_at, bank_at, money ; objet -> quantité dans les sacs et la banque)."""
        meta = self.conn.execute("SELECT * FROM game_inventory WHERE character_id = ?", (character_id,)).fetchone()
        rows = self.conn.execute(
            "SELECT item_id, bags + bank AS n FROM game_items WHERE character_id = ?", (character_id,)
        )
        return meta, {r["item_id"]: r["n"] for r in rows if r["n"] > 0}

    def ah_snapshot_time(self) -> int | None:
        row = self.conn.execute("SELECT MAX(ts) FROM ah_latest").fetchone()
        return row[0] if row and row[0] else None

    def ah_classes(self) -> list[tuple[int, str, list[tuple[int, str, int]]]]:
        """Types des objets en vente : [(classe, nom, [(sous-classe, nom, nombre d'objets)])], par nombre décroissant."""
        rows = self.conn.execute(
            """SELECT i.class_id, i.class_name, i.subclass_id, i.subclass_name, COUNT(*) AS n
               FROM ah_latest l JOIN ah_items i ON i.id = l.item_id
               WHERE i.class_id IS NOT NULL GROUP BY i.class_id, i.subclass_id"""
        ).fetchall()
        classes: dict[int, tuple[str, list[tuple[int, str, int]]]] = {}
        for r in rows:
            name, subs = classes.setdefault(r["class_id"], (r["class_name"] or "?", []))
            if r["subclass_id"] is not None:
                subs.append((r["subclass_id"], r["subclass_name"] or "?", r["n"]))
        result = [(cid, name, sorted(subs, key=lambda s: -s[2])) for cid, (name, subs) in classes.items()]
        return sorted(result, key=lambda c: -sum(s[2] for s in c[2]))

    _AH_SORTS = {
        "nom": "COALESCE(i.search, '~') ASC, l.item_id",
        "prix": "l.min_price ASC", "-prix": "l.min_price DESC",
        "quantite": "l.quantity DESC", "annonces": "l.listings DESC",
    }

    def ah_listing(
        self, query: str = "", class_id: int | None = None, subclass_id: int | None = None,
        favorites_of: int | None = None, sort: str = "nom", limit: int = 50, offset: int = 0,
        item_ids: list[int] | None = None,
    ) -> tuple[list[sqlite3.Row], int]:
        """Objets en vente filtrés (recherche déjà normalisée, type, favoris), avec le prix d'il y a 24 h.
        Renvoie (lignes de la page, nombre total)."""
        where, args = ["1"], []
        if query:
            where.append("i.search LIKE ?")
            args.append(f"%{query}%")
        if class_id is not None:
            where.append("i.class_id = ?")
            args.append(class_id)
        if subclass_id is not None:
            where.append("i.subclass_id = ?")
            args.append(subclass_id)
        if favorites_of is not None:
            where.append("l.item_id IN (SELECT item_id FROM ah_favorites WHERE user_id = ?)")
            args.append(favorites_of)
        if item_ids is not None:
            where.append(f"l.item_id IN ({','.join('?' * len(item_ids)) or 'NULL'})")
            args.extend(item_ids)
        joins = "FROM ah_latest l LEFT JOIN ah_items i ON i.id = l.item_id"
        condition = " AND ".join(where)
        total = self.conn.execute(f"SELECT COUNT(*) {joins} WHERE {condition}", args).fetchone()[0]
        rows = self.conn.execute(
            f"""SELECT l.*, i.name, i.quality, i.class_name, i.subclass_name, ic.url AS icon,
                       (SELECT p.min_price FROM ah_prices p WHERE p.item_id = l.item_id AND p.ts <= l.ts - 86400
                        ORDER BY p.ts DESC LIMIT 1) AS min_price_24h
                {joins} LEFT JOIN item_icons ic ON ic.item_id = l.item_id
                WHERE {condition}
                ORDER BY {self._AH_SORTS.get(sort, self._AH_SORTS['nom'])} LIMIT ? OFFSET ?""",
            [*args, limit, offset],
        ).fetchall()
        return rows, total

    def ah_item(self, item_id: int) -> sqlite3.Row | None:
        """Un objet (base locale, dernier relevé s'il est en vente, icône)."""
        return self.conn.execute(
            """SELECT x.item_id, i.name, i.quality, i.class_id, i.class_name, i.subclass_name, i.level,
                      i.required_level, i.sell_price, l.ts, l.min_price, l.median_price, l.quantity, l.listings,
                      ic.url AS icon
               FROM (SELECT ? AS item_id) x
               LEFT JOIN ah_items i ON i.id = x.item_id LEFT JOIN ah_latest l ON l.item_id = x.item_id
               LEFT JOIN item_icons ic ON ic.item_id = x.item_id
               WHERE i.id IS NOT NULL OR l.item_id IS NOT NULL""",
            (item_id,),
        ).fetchone()

    def ah_history(self, item_id: int, since: int) -> list[tuple[int, int, int, int, int]]:
        """[(ts, prix mini, médiane, quantité, annonces)] depuis `since`, du plus ancien au plus récent."""
        rows = self.conn.execute(
            """SELECT ts, min_price, median_price, quantity, listings FROM ah_prices
               WHERE item_id = ? AND ts >= ? ORDER BY ts""",
            (item_id, since),
        )
        return [tuple(r) for r in rows]

    def ah_favorite_ids(self, user_id: int) -> set[int]:
        return {r[0] for r in self.conn.execute("SELECT item_id FROM ah_favorites WHERE user_id = ?", (user_id,))}

    def toggle_ah_favorite(self, user_id: int, item_id: int) -> bool:
        """Ajoute ou retire un favori ; renvoie True s'il est désormais en favori."""
        with self.conn:
            removed = self.conn.execute(
                "DELETE FROM ah_favorites WHERE user_id = ? AND item_id = ?", (user_id, item_id)
            ).rowcount
            if removed:
                return False
            self.conn.execute("INSERT INTO ah_favorites (user_id, item_id) VALUES (?, ?)", (user_id, item_id))
        return True

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
