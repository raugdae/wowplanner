from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from wowplanner.instances import InstanceRegistry, parse_wikitext
from wowplanner.roles import RoleEmojis, default_composition, resolve_composition
from wowplanner.timeparse import parse_when

PARIS = ZoneInfo("Europe/Paris")

WIKITEXT = """
==Dungeons and raids==
<ul class="side-by-side"><li>
{| class="darktable zebra sortable"
|+ Forever dungeons (10-39)
! Dungeon !! Abbr || Location !! Level !! New?
|-
| [[Hall of Thanes (instance)|The Hall of Thanes]] || HoT || [[Ironforge]] || 13-18 || {{text|uncommon|NEW}}
|-
| [[Deadmines (Classic)|Deadmines]] || DM/VC || [[Westfall (Classic)|Westfall]] || 18-24 || Old
|-
| [[Razorfen Kraul (Classic)|Razorfen Kraul]] || RFK || [[Barrens (Classic)|Barrens]] ||30-36 || Old
|-
| [[Temple of Atal'Hakkar (Classic)|Temple of Atal'Hakkar]] (Sunken Temple) || ST || [[Swamp of Sorrows (Classic)|Swamp of Sorrows]] || 52-58 || Old
|}
</li></ul>
{| class="darktable zebra sortable"
|+ Forever raids
|-
! Raid !! Abbr !! Location !! Limit !! New?
|-
| [[Barrow Deeps (instance)|Barrow Deeps]] || BD || [[Mount Hyjal (Forever)|Mount Hyjal]] || 10 || {{text|uncommon|NEW}}
|-
| [[Onyxia's Lair (Classic)|Onyxia's Lair]] || Ony || [[Dustwallow Marsh (Classic)|Dustwallow Marsh]] || 40 || Old
|}
"""


def test_parse_wikitext():
    instances = parse_wikitext(WIKITEXT)
    names = [i.name for i in instances]
    assert names == [
        "The Hall of Thanes",
        "Deadmines",
        "Razorfen Kraul",
        "Temple of Atal'Hakkar (Sunken Temple)",
        "Barrow Deeps",
        "Onyxia's Lair",
    ]
    hot = instances[0]
    assert (hot.abbr, hot.kind, hot.size, hot.location, hot.levels, hot.new) == (
        "HoT", "dungeon", 5, "Ironforge", "13-18", True
    )
    assert instances[2].levels == "30-36"
    ony = instances[-1]
    assert (ony.kind, ony.size, ony.new) == ("raid", 40, False)


def test_registry_default_list_and_search(tmp_path):
    reg = InstanceRegistry(tmp_path / "cache.json")
    reg.load()
    assert len(reg.all) >= 30
    assert reg.get("ony").name == "Onyxia's Lair"
    assert reg.get("vc").name == "Deadmines"
    assert reg.search("brd")[0].name == "Blackrock Depths"


@pytest.mark.parametrize(
    "args, expected",
    [
        ((None, 5, None, None, None), {"tank": 1, "heal": 1, "dps": 3}),
        ((None, 40, None, None, None), {"tank": 4, "heal": 10, "dps": 26}),
        ((None, 20, 2, None, None), {"tank": 2, "heal": 5, "dps": 13}),
        ((None, 20, 2, 4, 10), {"tank": 2, "heal": 4, "dps": 10}),
        ((12, 20, None, None, None), {"tank": 1, "heal": 3, "dps": 8}),
        ((5, None, None, None, 4), {"tank": 1, "heal": 0, "dps": 4}),
    ],
)
def test_resolve_composition(args, expected):
    assert resolve_composition(*args) == expected


@pytest.mark.parametrize(
    "args",
    [
        (None, None, None, None, None),  # instance inconnue sans taille
        (5, None, 1, 1, 1),  # incohérent
        (5, None, 3, 3, None),  # trop de places
    ],
)
def test_resolve_composition_errors(args):
    with pytest.raises(ValueError):
        resolve_composition(*args)


def test_default_composition_sums():
    for n in range(1, 41):
        assert sum(default_composition(n).values()) == n


def test_parse_when():
    now = datetime(2026, 11, 11, 14, 0, tzinfo=PARIS)
    assert parse_when("25/12/2026", "21h30", PARIS, now) == datetime(2026, 12, 25, 21, 30, tzinfo=PARIS)
    assert parse_when("25/12", "21:00", PARIS, now).year == 2026
    assert parse_when("05/01", "21h", PARIS, now).year == 2027  # date passée → année suivante
    assert parse_when("demain", "20", PARIS, now) == datetime(2026, 11, 12, 20, 0, tzinfo=PARIS)
    for bad in [("01/01/2020", "21:00"), ("32/01", "21:00"), ("25/12", "25:00"), ("noel", "21:00")]:
        with pytest.raises(ValueError):
            parse_when(*bad, PARIS, now)


def test_role_emojis():
    emojis = RoleEmojis({"tank": "🛡️", "heal": "⛑️", "dps": "⚔️"})
    assert emojis.display("dps") == "⚔️"
    custom = RoleEmojis({"tank": "<:tank:123456789012345678>", "heal": "⛑️", "dps": "⚔️"})
    assert custom["tank"].id == 123456789012345678


def test_gamedata():
    from wowplanner.gamedata import CLASSES, RACES, can_play, race_allows

    assert can_play("paladin", "tank") and can_play("druide", "heal")
    assert not can_play("chaman", "tank") and not can_play("mage", "heal")
    assert all(can_play(c, "dps") for c in CLASSES)  # tout le monde peut DPS
    assert race_allows("mort_vivant", "paladin")  # nouveauté Forever
    assert race_allows("nain", "chaman")  # nouveauté Forever
    assert not race_allows("tauren", "mage")
    for _, classes in RACES.values():
        assert classes <= CLASSES.keys()


def test_db_characters_and_signups(tmp_path):
    import sqlite3

    from wowplanner.db import Database

    db = Database(tmp_path / "t.db")
    db.create_event(_event(10, 2_000_000))
    tank = db.add_character(7, "Grommash", "guerrier", "orc")
    healer = db.add_character(7, "Aelys", "pretre", "humain")
    with pytest.raises(sqlite3.IntegrityError):
        db.add_character(7, "grommash", "mage", "orc")  # même nom, casse différente
    db.add_character(8, "Grommash", "guerrier", "orc")  # un autre joueur peut avoir le même nom
    assert [c.name for c in db.get_characters(7)] == ["Aelys", "Grommash"]

    db.upsert_signup(10, 7, "tank", "Raug", tank.id)
    db.upsert_signup(10, 9, "dps", "Bob")
    first = db.get_signups(10)[0]
    assert (first.character_name, first.character_class) == ("Grommash", "guerrier")

    # Changer de perso dans le même rôle garde la place ; changer de rôle la fait perdre.
    db.upsert_signup(10, 7, "tank", "Raug", tank.id)
    assert db.get_signups(10)[0].user_id == 7
    db.upsert_signup(10, 7, "heal", "Raug", healer.id)
    assert [s.user_id for s in db.get_signups(10)] == [9, 7]

    # Supprimer le perso garde l'inscription, sans perso.
    assert db.delete_character(7, healer.id) == [10]
    signup = next(s for s in db.get_signups(10) if s.user_id == 7)
    assert signup.role == "heal" and signup.character_id is None and signup.character_name is None
    db.close()


def _event(message_id, starts_at, **kw):
    from wowplanner.db import Event

    return Event(
        message_id=message_id, guild_id=1, channel_id=2, creator_id=3, instance="Deadmines", kind="dungeon",
        levels=None, starts_at=starts_at, caps={"tank": 1, "heal": 1, "dps": 3}, created_at=0, **kw,
    )


def test_db_reminder_and_voice_queries(tmp_path):
    from wowplanner.db import Database

    db = Database(tmp_path / "t.db")
    now = 1_000_000
    db.create_event(_event(10, now + 20 * 60))  # dans 20 min
    db.create_event(_event(11, now + 2 * 3600))  # dans 2 h
    db.create_event(_event(12, now - 60))  # déjà commencée
    db.create_event(_event(13, now + 10 * 60, cancelled=True))

    assert [e.message_id for e in db.events_to_remind(now, 30 * 60)] == [10]
    db.mark_reminded(10)
    assert db.events_to_remind(now, 30 * 60) == []

    # 12 a commencé il y a 1 min : rattrapée tant qu'on est dans la tolérance.
    assert [e.message_id for e in db.events_needing_voice(now, 15 * 60, 3600)] == [12]
    assert [e.message_id for e in db.events_needing_voice(now, 30 * 60, 3600)] == [12, 10]
    db.set_voice_channel(10, 555)
    db.set_voice_channel(12, 0)  # création échouée : on ne réessaie pas
    assert db.events_needing_voice(now, 30 * 60, 3600) == []
    assert [e.voice_channel_id for e in db.events_with_voice()] == [555]
    db.close()


def test_db_migration_adds_columns(tmp_path):
    import sqlite3

    from wowplanner.db import Database

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """CREATE TABLE events (message_id INTEGER PRIMARY KEY, guild_id INTEGER NOT NULL, channel_id INTEGER NOT NULL,
           creator_id INTEGER NOT NULL, instance TEXT NOT NULL, kind TEXT NOT NULL, levels TEXT,
           starts_at INTEGER NOT NULL, tank_cap INTEGER NOT NULL, heal_cap INTEGER NOT NULL, dps_cap INTEGER NOT NULL,
           description TEXT, cancelled INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL);
           CREATE TABLE signups (message_id INTEGER NOT NULL, user_id INTEGER NOT NULL, role TEXT NOT NULL,
           signed_at REAL NOT NULL, PRIMARY KEY (message_id, user_id));
           INSERT INTO events VALUES (1, 1, 2, 3, 'Deadmines', 'dungeon', NULL, 100, 1, 1, 3, NULL, 0, 0);"""
    )
    conn.close()
    db = Database(path)
    ev = db.get_event(1)
    assert ev.reminder_sent is False and ev.voice_channel_id is None
    db.close()


def test_db_professions_battletags_and_members(tmp_path):
    from wowplanner.db import Database

    db = Database(tmp_path / "t.db")
    guild, other_guild = 100, 200
    a = db.add_character(1, "Grommash", "guerrier", "orc", "tank")
    b = db.add_character(2, "Aelys", "pretre", "humain")
    c = db.add_character(3, "Stranger", "mage", "gnome")
    db.touch_member(guild, 1)
    db.touch_member(guild, 2)
    db.touch_member(other_guild, 3)

    db.set_profession(a.id, "forge", 150)
    db.set_profession(a.id, "forge", 285)  # mise à jour du niveau
    db.set_profession(a.id, "minage", None)
    db.set_profession(b.id, "forge", None)
    db.set_profession(c.id, "forge", 300)  # autre serveur : invisible ici

    assert db.get_character(a.id).professions == {"forge": 285, "minage": None}
    assert db.get_character(a.id).preferred_role == "tank"
    found = db.characters_with_profession(guild, "forge")
    assert [(ch.name, skill) for ch, skill in found] == [("Grommash", 285), ("Aelys", None)]
    assert db.remove_profession(a.id, "minage") and not db.remove_profession(a.id, "minage")

    db.set_preferred_role(b.id, "heal")
    assert db.get_character(b.id).preferred_role == "heal"

    db.set_battletag(1, "Raug#2134")
    db.set_battletag(3, "Other#1111")
    assert db.battletags(guild) == [(1, "Raug#2134")]
    db.set_battletag(1, None)
    assert db.battletags(guild) == []

    db.delete_character(1, a.id)  # les métiers partent avec le perso
    assert db.conn.execute("SELECT COUNT(*) FROM character_professions WHERE character_id = ?", (a.id,)).fetchone()[0] == 0
    db.close()


def test_battletag_format():
    from wowplanner.cogs.players import BATTLETAG_RE

    for ok in ("Raug#2134", "Élodie#12345", "abc#123"):
        assert BATTLETAG_RE.match(ok), ok
    for bad in ("Raug", "1Raug#2134", "Ra#2134", "Raug#", "Raug Dae#2134", "TrèsTrèsLongNom#1234"):
        assert not BATTLETAG_RE.match(bad), bad


def test_signup_choices_isolated_per_event(tmp_path):
    """/supprimer inscrit ne propose que les inscrits de la sortie choisie."""
    from types import SimpleNamespace

    from wowplanner.cogs.events import EventsCog
    from wowplanner.db import Database

    db = Database(tmp_path / "t.db")
    ev_a, ev_b = 111111111111111111, 222222222222222222
    db.create_event(_event(ev_a, 2_000_000))
    db.create_event(_event(ev_b, 2_000_000))
    db.upsert_signup(ev_a, 1, "tank", "Raug")
    db.upsert_signup(ev_a, 2, "dps", "Bob")
    db.upsert_signup(ev_b, 2, "heal", "Bob")  # Bob est inscrit aux deux sorties

    bot = SimpleNamespace(db=db, role_emojis=None, instances=None)
    cog = EventsCog(bot)
    assert [c.value for c in cog.signup_choices(str(ev_b), "")] == ["2"]
    assert sorted(c.value for c in cog.signup_choices(str(ev_a), "")) == ["1", "2"]
    assert cog.signup_choices(None, "") == []  # sortie pas encore choisie : rien
    assert [c.value for c in cog.signup_choices(str(ev_a), "raug")] == ["1"]
    db.close()
