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


def test_character_name_normalization():
    from wowplanner.cogs.characters import normalize_name

    assert normalize_name("grommash") == "Grommash"
    assert normalize_name("  grommash HURLENFER ") == "Grommash Hurlenfer"
    assert normalize_name("élodie dupré") == "Élodie Dupré"
    for bad in ("Grommash  Hurlenfer", "Jean Paul Dupont", "Grom1", "Gr-om", "G Hurlenfer", "a" * 33):
        assert normalize_name(bad) is None, bad


def test_ephemeral_cleaner():
    import asyncio
    import datetime
    from types import SimpleNamespace

    import discord

    from wowplanner.ephemeral import EphemeralCleaner

    deleted = []
    now = discord.utils.utcnow()

    def inter(id_, user, kind="command", ephemeral_msg=False, age_min=0, in_dm=False):
        async def delete_original_response():
            deleted.append(id_)

        message = SimpleNamespace(flags=SimpleNamespace(ephemeral=ephemeral_msg))
        return SimpleNamespace(
            id=id_,
            guild_id=None if in_dm else 42,
            user=SimpleNamespace(id=user),
            type=discord.InteractionType.application_command if kind == "command" else discord.InteractionType.component,
            message=None if kind == "command" else message,
            expires_at=now + datetime.timedelta(minutes=15 - age_min),
            delete_original_response=delete_original_response,
        )

    async def scenario():
        c = EphemeralCleaner()
        await c.on_interaction(inter(1, user=7))  # /liste persos
        await c.on_interaction(inter(2, user=7, kind="button"))  # clic Heal sur une sortie → efface 1
        await c.on_interaction(inter(3, user=7, kind="button", ephemeral_msg=True))  # choix du perso : on garde 2
        await c.on_interaction(inter(4, user=8))  # autre joueur : n'efface rien de 7
        await c.on_interaction(inter(5, user=7))  # nouvelle commande → efface 2
        await c.on_interaction(inter(8, user=7, kind="button", in_dm=True))  # page ▶ en MP : ignoré
        await c.on_interaction(inter(9, user=7))  # nouvelle commande → efface 5, jamais le MP (8)
        c._last[7] = inter(6, user=7, age_min=15)  # réponse expirée : plus supprimable
        await c.on_interaction(inter(7, user=7))

    asyncio.run(scenario())
    assert deleted == [1, 2, 5]


def test_character_slug():
    from wowplanner.armory import character_slug

    assert character_slug("Grommash Hurlenfer") == "grommash-hurlenfer"
    assert character_slug("  Élodie  ") == "élodie"


def test_armory_client_against_fake_server():
    """Jeton demandé une fois puis réutilisé, bons paramètres, 404 → ArmoryError."""
    import asyncio

    import aiohttp
    from aiohttp import web

    from wowplanner.armory import ArmoryClient, ArmoryError

    calls = {"token": 0, "paths": []}

    async def token(request):
        calls["token"] += 1
        assert request.headers["Authorization"].startswith("Basic ")
        return web.json_response({"access_token": "tok", "expires_in": 86399})

    async def character(request):
        assert request.headers["Authorization"] == "Bearer tok"
        calls["paths"].append((request.path, request.query["namespace"], request.query["locale"]))
        if request.match_info["slug"] == "inconnu-perso":
            return web.json_response({"code": 404}, status=404)
        return web.json_response({"name": "Grommash", "surname": "Hurlenfer", "level": 42})

    async def scenario():
        app = web.Application()
        app.router.add_post("/token", token)
        app.router.add_get("/profile/wow/character/{slug}{rest:.*}", character)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        try:
            async with aiohttp.ClientSession() as session:
                api = ArmoryClient(session, "id", "secret", "EU", base_url=base, token_url=f"{base}/token")
                data = await api.character("Grommash Hurlenfer")
                assert data["level"] == 42
                await api.character("Grommash Hurlenfer", "/professions")
                try:
                    await api.character("Inconnu Perso")
                    raise AssertionError("une 404 doit lever ArmoryError")
                except ArmoryError as exc:
                    assert exc.status == 404
        finally:
            await runner.cleanup()

    asyncio.run(scenario())
    assert calls["token"] == 1  # jeton réutilisé
    assert calls["paths"][0] == ("/profile/wow/character/grommash-hurlenfer", "profile-forever-eu", "fr_FR")
    assert calls["paths"][1][0] == "/profile/wow/character/grommash-hurlenfer/professions"


def test_armory_probe_summaries_do_not_crash():
    from wowplanner.armory_probe import summarize

    profile = {"name": "Grommash", "surname": "Hurlenfer", "level": 42, "race": {"name": "Orc"},
               "character_class": {"name": "Guerrier"}, "average_item_level": 40, "equipped_item_level": 41}
    assert "niveau 42 · Orc Guerrier" in summarize("", profile)
    stats = {"health": 3200, "strength": {"base": 120, "effective": 150}, "melee_crit": {"value": 7.5}}
    assert summarize("/statistics", stats)[:3] == ["health : 3200", "strength : 150", "melee_crit : 7.5"]
    profs = {"primaries": [{"profession": {"name": "Forge"}, "tiers": [{"skill_points": 285, "max_skill_points": 300}]}],
             "secondaries": [{"profession": {"name": "Cuisine"}, "skill_points": 150, "max_skill_points": 300}]}
    assert summarize("/professions", profs) == [
        "primaries : Forge 285/300 (1 palier(s))",
        "secondaries : Cuisine 150/300 (0 palier(s))",
    ]
    assert summarize("/professions", {"_links": {}})[0].startswith("aucun métier")
    equipment = {"equipped_items": [{"slot": {"name": "Tête"}, "name": "Heaume", "level": {"value": 45}}]}
    assert summarize("/equipment", equipment) == ["1 pièces", "Tête : Heaume (ilvl 45)"]


def _sheet():
    from wowplanner.armory import ArmorySheet

    return ArmorySheet(
        profile={"name": "Hollie", "surname": "Tétine", "level": 20, "character_class": {"id": 5, "name": "Prêtre"},
                 "race": {"id": 95, "name": "Éolide de l'Ordre suprême"}, "faction": {"name": "Alliance"}},
        professions={
            "primaries": [{"profession": {"id": 171, "name": "Alchemy"}, "tiers": [{"skill_points": 139, "max_skill_points": 150}]},
                          {"profession": {"id": 2933, "name": None}, "tiers": [{"skill_points": 5}]}],  # inconnu : ignoré
            "secondaries": [{"profession": {"id": 185, "name": "Cooking"}, "tiers": [{"skill_points": 54, "max_skill_points": 75}]}],
        },
        specializations={"specialization_groups": [
            {"is_active": False, "specializations": [{"specialization": {"name": "Sacré"}, "spent_points": 30}]},
            {"is_active": True, "specializations": [
                {"specialization": {"name": "Discipline"}, "spent_points": 5},
                {"specialization": {"name": "Magie de l'ombre"}, "spent_points": 11},
            ]},
        ]},
        media={"assets": [{"key": "avatar", "value": "https://render/avatar.jpg"}]},
    )


def test_armory_sheet_parsing():
    sheet = _sheet()
    assert sheet.full_name == "Hollie Tétine"
    assert (sheet.class_key, sheet.race_key) == ("pretre", "skyborne")
    assert sheet.active_spec == ("Magie de l'ombre", 11)  # groupe actif, arbre le plus investi
    assert sheet.asset("avatar") == "https://render/avatar.jpg" and sheet.asset("main-raw") is None
    assert sheet.profession_skills() == {"alchimie": (139, 150), "cuisine": (54, 75)}
    sheet.professions = None
    assert sheet.profession_skills() is None  # métiers illisibles : on ne touche à rien


def test_armory_apply_replaces_professions_and_warns(tmp_path):
    from types import SimpleNamespace

    from wowplanner.cogs.armory import ArmoryCog, build_armory_embed
    from wowplanner.db import Database

    db = Database(tmp_path / "t.db")
    c = db.add_character(1, "Hollie Tétine", "mage", "skyborne")
    db.set_profession(c.id, "forge", 10)  # saisie manuelle, remplacée par l'armurerie
    cog = ArmoryCog(SimpleNamespace(db=db))
    result = cog.apply(c, _sheet())
    synced = db.get_character(c.id)
    assert synced.professions == {"alchimie": 139, "cuisine": 54}
    assert synced.armory_synced_at is not None
    assert result.professions_synced and len(result.warnings) == 1  # classe différente, race identique
    assert "Prêtre" in result.warnings[0]
    embed = build_armory_embed(_sheet(), [1])
    assert len(embed) < 6000 and embed.title == "Hollie Tétine"
    db.close()


def test_recipes_db_and_pages(tmp_path):
    from wowplanner.db import Database
    from wowplanner.recipes import crafters_text, filter_recipes, recipe_field

    db = Database(tmp_path / "t.db")
    hollie = db.add_character(1, "Hollie Tétine", "pretre", "humain")
    grom = db.add_character(2, "Grommash Hurlenfer", "guerrier", "orc")
    stranger = db.add_character(3, "Autre Serveur", "mage", "gnome")
    db.touch_member(42, 1)
    db.touch_member(42, 2)  # 3 n'est pas sur ce serveur
    db.replace_character_recipes(hollie.id, {"alchimie": [(1379, "Minor Mana Potion"), (54211, "Elixir of Minor Force")]})
    db.replace_character_recipes(grom.id, {"alchimie": [(1379, "Minor Mana Potion")]})
    db.replace_character_recipes(stranger.id, {"alchimie": [(9999, "Secret")]})

    assert sorted(db.recipes_missing_details("alchimie")) == [1379, 9999, 54211]
    db.set_recipe_details(1379, "Potion de mana mineure", [(1, "Mage royal"), (1, "Fiole vide")])
    recipes = {r.id: r for r in db.guild_recipes(42, "alchimie")}
    assert set(recipes) == {1379, 54211}  # la recette de l'autre serveur n'apparaît pas
    assert recipes[1379].crafters == ["Grommash Hurlenfer", "Hollie Tétine"]
    assert recipes[1379].reagents == [(1, "Mage royal"), (1, "Fiole vide")]
    assert recipes[54211].name == "Elixir of Minor Force" and recipes[54211].reagents is None  # pas encore récupérée

    assert [r.id for r in filter_recipes(list(recipes.values()), "POTION")] == [1379]
    card = recipe_field(recipes[1379])
    assert card.name == "Potion de mana mineure" and card.inline
    assert card.value == "1× Mage royal\n1× Fiole vide\n👥 Grommash, Hollie"
    assert "composants inconnus" in recipe_field(recipes[54211]).value
    assert crafters_text([f"Perso{i} X" for i in range(8)]) == "Perso0, Perso1, Perso2, Perso3, Perso4, Perso5 +2"

    # Resynchro : la liste des recettes du perso est remplacée, pas cumulée.
    db.replace_character_recipes(grom.id, {"alchimie": []})
    assert db.guild_recipes(42, "alchimie")[0].crafters == ["Hollie Tétine"]
    db.close()


def test_recipe_families_and_pages():
    from wowplanner.db import GuildRecipe
    from wowplanner.recipes import MAX_FIELDS_PER_PAGE, build_pages, filter_recipes, group_by_family

    def r(i, name):
        return GuildRecipe(i, name, [(1, "Fiole vide")], ["Hollie Tétine"])

    recipes = filter_recipes([
        r(1, "Élixir de Force mineure"), r(2, "Elixir de Sagesse"), r(3, "Elixir d'Agilité mineure"),
        r(4, "Potion de mana mineure"), r(5, "Potion de soins"), r(6, "Potion de Nage rapide"),
        r(7, "Huile de feu"), r(8, "Acide sulfurique"),
    ], None)
    families = group_by_family(recipes)
    # « Élixir » et « Elixir » forment une seule famille, libellé accentué au pluriel ; les isolées vont dans « Autres ».
    assert [(f, [x.id for x in m]) for f, m in families] == [
        ("Élixirs", [3, 1, 2]), ("Potions", [4, 6, 5]), ("Autres", [8, 7]),
    ]
    page = build_pages(recipes)[0]
    assert [f.name for f in page if not f.inline] == ["── Élixirs (3) ──", "── Potions (3) ──", "── Autres (2) ──"]

    # Pagination : limites Discord respectées, aucune recette perdue, titre « (suite) » en haut des pages suivantes.
    many = filter_recipes([r(i, f"Potion numéro {i:03d}") for i in range(200)], None)
    pages = build_pages(many)
    assert len(pages) > 1
    assert all(len(p) <= MAX_FIELDS_PER_PAGE and sum(len(f.name) + len(f.value) for f in p) < 6000 for p in pages)
    assert sum(1 for p in pages for f in p if f.inline) == 200
    assert all(not p[0].inline for p in pages) and pages[1][0].name == "── Potions (suite) ──"


def test_recipe_messages_respect_discord_limits():
    from wowplanner.cogs.armory import recipe_messages
    from wowplanner.db import GuildRecipe
    from wowplanner.recipes import build_pages, filter_recipes

    many = filter_recipes([
        GuildRecipe(i, f"Potion de protection contre le feu {i:03d}",
                    [(1, "Doulourante"), (1, "Chardonnier"), (1, "Fiole plombée")],
                    ["Hollie Tétine", "Xfalsia Truc", "Gwoo Machin", "Feuille Bidule"])
        for i in range(300)
    ], None)
    messages = recipe_messages(build_pages(many), "⚒️ Alchimie — 300 recette(s)")
    assert len(messages) > 1
    for embeds in messages:
        assert 1 <= len(embeds) <= 10
        assert sum(len(e) for e in embeds) <= 6000  # limite Discord par message
        assert all(len(e.fields) <= 25 for e in embeds)
        assert embeds[0].title and embeds[-1].footer.text.startswith("Page ")
    assert sum(1 for m in messages for e in m for f in e.fields if f.inline) == 300
