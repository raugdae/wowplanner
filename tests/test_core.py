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


def test_role_emojis_variation_selector():
    import discord

    emojis = RoleEmojis({"tank": "🛡️", "heal": "⛑️", "dps": "⚔️"})
    assert emojis.role_for(discord.PartialEmoji(name="\U0001F6E1")) == "tank"  # sans U+FE0F
    assert emojis.role_for("⚔️") == "dps"
    assert emojis.role_for("👍") is None
    custom = RoleEmojis({"tank": "<:tank:123>", "heal": "⛑️", "dps": "⚔️"})
    assert custom.role_for(discord.PartialEmoji(name="tank", id=123)) == "tank"
