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
    assert ev.reminder_sent is False and ev.voice_channel_id is None and ev.creator_name is None
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

    db.replace_professions(a.id, {"forge": 150, "couture": 20})
    db.replace_professions(a.id, {"forge": 285, "minage": None})  # resynchro : tout est remplacé
    db.replace_professions(b.id, {"forge": None})
    db.replace_professions(c.id, {"forge": 300})  # autre serveur : invisible ici

    assert db.get_character(a.id).professions == {"forge": 285, "minage": None}
    assert db.get_character(a.id).preferred_role == "tank"
    found = db.characters_with_profession(guild, "forge")
    assert [(ch.name, skill) for ch, skill in found] == [("Grommash", 285), ("Aelys", None)]

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
        await c.on_interaction(inter(1, user=7))  # /liste events
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
    assert sheet.asset("avatar") == "https://render/avatar.jpg" and sheet.asset("main-raw") is None
    assert sheet.profession_skills() == {"alchimie": (139, 150), "cuisine": (54, 75)}
    sheet.professions = None
    assert sheet.profession_skills() is None  # métiers illisibles : on ne touche à rien


def test_armory_apply_replaces_professions_and_warns(tmp_path):
    from types import SimpleNamespace

    from wowplanner.cogs.armory import ArmoryCog
    from wowplanner.db import Database

    db = Database(tmp_path / "t.db")
    c = db.add_character(1, "Hollie Tétine", "mage", "skyborne")
    db.replace_professions(c.id, {"forge": 10})  # ancienne valeur, remplacée par l'armurerie
    cog = ArmoryCog(SimpleNamespace(db=db))
    result = cog.apply(c, _sheet())
    synced = db.get_character(c.id)
    assert synced.professions == {"alchimie": 139, "cuisine": 54}
    assert synced.armory_synced_at is not None
    assert result.professions_synced and len(result.warnings) == 1  # classe différente, race identique
    assert "Prêtre" in result.warnings[0] and "recrée" in result.warnings[0]
    db.close()


def test_recipes_db_and_search(tmp_path):
    from wowplanner.db import Database
    from wowplanner.recipes import filter_recipes

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
    assert recipes[1379].reagents == [(1, "Mage royal", None), (1, "Fiole vide", None)]  # ancien format : sans id
    assert recipes[54211].name == "Elixir of Minor Force" and recipes[54211].reagents is None  # pas encore récupérée

    assert [r.id for r in filter_recipes(list(recipes.values()), "POTION")] == [1379]
    assert db.all_recipe_ids() == [1379, 9999, 54211]  # /admin sync redemande tout, tous serveurs confondus

    # Resynchro : la liste des recettes du perso est remplacée, pas cumulée.
    db.replace_character_recipes(grom.id, {"alchimie": []})
    assert db.guild_recipes(42, "alchimie")[0].crafters == ["Hollie Tétine"]
    db.close()


def test_recipe_families():
    from wowplanner.db import GuildRecipe
    from wowplanner.recipes import filter_recipes, group_by_family

    def r(i, name):
        return GuildRecipe(i, name, [(1, "Fiole vide", 3371)], ["Hollie Tétine"])

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


class _FakeResponse:
    def __init__(self, sink):
        self.sink, self.done = sink, False

    def is_done(self):
        return self.done

    async def defer(self, **kw):
        self.done = True

    async def send_message(self, text=None, **kw):
        self.done = True
        self.sink.append(text)


class _FakeFollowup:
    def __init__(self, sink):
        self.sink = sink

    async def send(self, text=None, **kw):
        self.sink.append(text)


def _fake_interaction(user_id, sent):
    from types import SimpleNamespace

    return SimpleNamespace(
        user=SimpleNamespace(id=user_id, display_name="Raug", mention=f"<@{user_id}>"),
        guild=SimpleNamespace(id=42), response=_FakeResponse(sent), followup=_FakeFollowup(sent),
    )


def _characters_with_fake_armory(tmp_path, found=True, enabled=True):
    from types import SimpleNamespace

    from wowplanner.armory import ArmoryError
    from wowplanner.cogs.armory import ArmoryCog
    from wowplanner.cogs.characters import CharacterCommands
    from wowplanner.db import Database

    db = Database(tmp_path / "t.db")

    class FakeClient:
        async def sheet(self, name, max_age=0):
            if not found:
                raise ArmoryError(404, "url")
            return _sheet()  # Prêtre Éolide avec Alchimie et Cuisine

    armory = ArmoryCog(SimpleNamespace(db=db))
    armory.client = FakeClient() if enabled else None
    bot = SimpleNamespace(db=db, get_cog=lambda name: armory if name == "ArmoryCog" else None)
    return db, CharacterCommands(bot)


def test_add_character_name_only_uses_armory_and_admin_owner(tmp_path):
    import asyncio
    from types import SimpleNamespace

    db, chars = _characters_with_fake_armory(tmp_path)
    sent, dms = [], []

    async def owner_send(text):
        dms.append(text)

    bob = SimpleNamespace(id=2, mention="<@2>", send=owner_send)
    asyncio.run(chars.add(_fake_interaction(1, sent), "hollie tétine", None, None, None, owner=bob))

    created = db.get_characters(2)  # le perso appartient à Bob, pas à l'admin
    assert [(c.name, c.wow_class, c.race) for c in created] == [("Hollie Tétine", "pretre", "skyborne")]
    assert created[0].professions == {"alchimie": 139, "cuisine": 54}
    assert db.get_characters(1) == []
    assert "ajouté pour <@2>" in sent[-1] and "reprise(s) de l'armurerie" in sent[-1]
    assert dms and "a ajouté ton perso **Hollie Tétine**" in dms[0]
    assert db.battletags(42) == [] and db.guild_characters(42)[0].user_id == 2  # Bob compte comme membre du serveur

    # Doublon chez Bob : refus, sans rien créer.
    asyncio.run(chars.add(_fake_interaction(1, sent), "Hollie Tétine", None, None, None, owner=bob))
    assert "a déjà un perso nommé" in sent[-1] and len(db.get_characters(2)) == 1
    db.close()


def test_add_character_name_only_needs_class_race_when_not_found(tmp_path):
    import asyncio

    for found, enabled, expected in ((False, True, "pas trouvé"), (True, False, "pas activée")):
        folder = tmp_path / f"{found}{enabled}"
        folder.mkdir()
        db, chars = _characters_with_fake_armory(folder, found=found, enabled=enabled)
        sent = []
        asyncio.run(chars.add(_fake_interaction(1, sent), "Inconnu Perso", None, None, None))
        assert expected in sent[-1] and "précise la **classe** et la **race**" in sent[-1]
        assert db.get_characters(1) == []
        # Avec classe et race données à la main, ça passe même sans armurerie.
        asyncio.run(chars.add(_fake_interaction(1, sent), "Inconnu Perso", "mage", "gnome", None))
        assert db.get_characters(1)[0].wow_class == "mage"
        db.close()


def test_subrecipes_are_expanded_with_scaled_quantities(tmp_path):
    """Lin → rouleau → sac : les composants fabriqués par une recette du serveur sont dépliés."""
    from wowplanner.db import Database
    from wowplanner.recipes import crafted_by_map, filter_recipes, reagent_lines

    db = Database(tmp_path / "t.db")
    hollie = db.add_character(1, "Hollie Tétine", "pretre", "humain")
    db.touch_member(42, 1)
    db.replace_character_recipes(hollie.id, {
        "couture": [(2359, "Bolt of Linen Cloth"), (9001, "Linen Bag"), (9002, "Thread")],
        "alchimie": [(9100, "Loop A")],
    })
    db.set_recipe_details(2359, "Rouleau d'étoffe de lin", [(2, "Etoffe de lin", 2589)], 2996, 1.0)
    db.set_recipe_details(9002, "Bobine de fil grossier", [(1, "Etoffe de lin", 2589)], 2320, 2.0)  # 2 bobines par craft
    db.set_recipe_details(9001, "Sac en lin", [(3, "Rouleau d'étoffe en lin", 2996), (3, "Bobine de fil grossier", 2320)], 4238, 1.0)
    db.set_recipe_details(9100, "Boucle", [(1, "Boucle", 7777)], 7777, 1.0)  # se fabrique elle-même : pas de boucle infinie
    assert db.recipes_missing_details() == []

    every = db.guild_recipes(42)  # tous métiers : les sous-recettes peuvent venir d'un autre métier
    crafted_by = crafted_by_map(every)
    bag = filter_recipes(db.guild_recipes(42, "couture"), "sac")[0]
    assert reagent_lines(bag.reagents, crafted_by, seen=frozenset({bag.id})) == [
        "3× Rouleau d'étoffe en lin",
        "\u2003\u2003↳ 6× Etoffe de lin",       # 3 rouleaux × 2 étoffes
        "3× Bobine de fil grossier",
        "\u2003\u2003↳ 2× Etoffe de lin",       # 3 bobines, 2 par craft → 2 crafts × 1 étoffe
    ]
    loop = next(r for r in every if r.id == 9100)
    assert reagent_lines(loop.reagents, crafted_by, seen=frozenset({loop.id})) == ["1× Boucle"]
    db.close()


def test_old_recipe_details_are_refetched_once(tmp_path):
    from wowplanner.db import Database

    db = Database(tmp_path / "t.db")
    c = db.add_character(1, "Hollie Tétine", "pretre", "humain")
    db.replace_character_recipes(c.id, {"alchimie": [(1379, "Minor Mana Potion")]})
    # Détails au format v1.4 (sans ids) : la recette doit être redemandée…
    db.conn.execute("UPDATE recipes SET name = 'Potion', reagents = '[[1, \"Mage royal\"]]', fetched_at = 1, details_version = NULL")
    assert db.recipes_missing_details() == [1379]
    # … puis plus jamais une fois au nouveau format.
    db.set_recipe_details(1379, "Potion de mana mineure", [(1, "Mage royal", 785)], 2455, 1.0)
    assert db.recipes_missing_details() == []
    db.close()


def test_website_pages_and_no_personal_info(tmp_path):
    """Le site public ne montre ni pseudo, ni id Discord, ni BattleTag, et échappe le HTML."""
    import asyncio

    import aiohttp

    from wowplanner.db import Database
    from wowplanner.web import WebSite

    db = Database(tmp_path / "t.db")
    discord_id, other_id = 123456789012345678, 999999999999999999
    hollie = db.add_character(discord_id, "Hollie Tétine", "pretre", "humain", "heal")
    db.add_character(discord_id, "Grommash Hurlenfer", "guerrier", "orc")
    db.add_character(other_id, "Autre Serveur", "mage", "gnome")  # membre d'un autre serveur : invisible
    db.touch_member(42, discord_id)
    db.touch_member(77, other_id)
    db.set_battletag(discord_id, "Raug#2134")
    db.replace_professions(hollie.id, {"alchimie": 139, "cuisine": 54})
    db.replace_character_recipes(hollie.id, {"alchimie": [(1, "Potion"), (2, "Oil")]})
    db.set_recipe_details(1, "Potion <script>alert(1)</script>", [(2, "Huile de bouche-noire", 500)], 600, 1.0)
    db.set_recipe_details(2, "Huile de bouche-noire", [(2, "Bouche-noire huileux", 700)], 500, 1.0)

    site = WebSite(db, lambda: 42)
    pages = {}

    async def scenario():
        await site.start("127.0.0.1", 0)
        port = next(iter(site._runner.sites))._server.sockets[0].getsockname()[1]
        async with aiohttp.ClientSession() as session:
            for path in ("/", f"/perso/{hollie.id}", "/metiers", "/metier/alchimie", "/donjons", "/aide", "/perso/99999",
                         "/metier/inconnu"):
                async with session.get(f"http://127.0.0.1:{port}{path}") as resp:
                    pages[path] = (resp.status, await resp.text())
        await site.stop()

    asyncio.run(scenario())
    db.close()

    assert pages["/"][0] == 200 and "Hollie Tétine" in pages["/"][1] and "Grommash Hurlenfer" in pages["/"][1]
    assert "Autre Serveur" not in pages["/"][1]
    assert pages[f"/perso/{hollie.id}"][0] == 200 and "Alchimie" in pages[f"/perso/{hollie.id}"][1]
    assert pages["/metier/alchimie"][0] == 200
    assert 'class="d1">4× Bouche-noire huileux' in pages["/metier/alchimie"][1]  # sous-recette dépliée
    assert pages["/perso/99999"][0] == 404 and pages["/metier/inconnu"][0] == 404
    for _, text in pages.values():
        assert str(discord_id) not in text and "Raug" not in text and "2134" not in text  # aucune info perso
        assert "<script>alert(1)</script>" not in text  # HTML échappé


def test_orders_db_and_rules(tmp_path):
    """Commandes : recettes commandables (pas les siennes), recherche, composants × quantité, droits."""
    from wowplanner.db import Database, Order
    from wowplanner.orders import allowed_actions, orderable, parse_quantity, scaled_reagents, search
    from wowplanner.recipes import crafted_by_map

    db = Database(tmp_path / "t.db")
    me, alice, bob = 1, 2, 3
    mine = db.add_character(me, "Moi Même", "mage", "gnome")
    a = db.add_character(alice, "Alice Alchi", "pretre", "humain")
    b = db.add_character(bob, "Bob Couture", "mage", "humain")
    for user in (me, alice, bob):
        db.touch_member(42, user)
    db.replace_character_recipes(mine.id, {"alchimie": [(1, "Mongoose")]})
    db.replace_character_recipes(a.id, {"alchimie": [(1, "Mongoose"), (2, "Minor")]})
    db.replace_character_recipes(b.id, {"couture": [(10, "Bolt"), (11, "Bag")]})
    db.set_recipe_details(1, "Élixir de la mangouste", [(2, "Fleur de feu", 100)], 900, 1.0)
    db.set_recipe_details(2, "Potion de soins mineure", [(1, "Pacifique", 101)], 901, 1.0)
    db.set_recipe_details(10, "Rouleau d'étoffe de lin", [(2, "Étoffe de lin", 200)], 300, 1.0)
    db.set_recipe_details(11, "Sac en lin", [(3, "Rouleau d'étoffe de lin", 300)], 301, 1.0)

    candidates = orderable(db.guild_recipes(42), db.recipe_crafters(42), me)
    assert {c.recipe.id for c in candidates} == {1, 2, 10, 11}
    mongoose = next(c for c in candidates if c.recipe.id == 1)
    assert [x.name for x in mongoose.crafters] == ["Alice Alchi"]  # pas mon propre perso
    # Alice ne voit pas la 2 (elle seule la connaît), mais voit la 1 (mon perso la connaît aussi).
    alice_view = orderable(db.guild_recipes(42), db.recipe_crafters(42), alice)
    assert {c.recipe.id for c in alice_view} == {1, 10, 11}

    assert [c.recipe.id for c in search(candidates, "mangouste")] == [1]
    assert [c.recipe.id for c in search(candidates, "lin")] == [10, 11]
    assert [c.recipe.id for c in search(candidates, "sac en lin")] == [11]  # nom exact
    assert search(candidates, "épée") == []

    bag = next(c for c in candidates if c.recipe.id == 11).recipe
    text = scaled_reagents(bag, 2, crafted_by_map(db.guild_recipes(42)))
    assert "6× Rouleau d'étoffe de lin" in text and "↳ 12× Étoffe de lin" in text

    assert parse_quantity("") == 1 and parse_quantity(" 5 ") == 5 and parse_quantity("x3") == 3
    assert parse_quantity("0") is None and parse_quantity("abc") is None and parse_quantity("101") is None

    order = db.create_order(Order(
        guild_id=42, requester_id=me, requester_name="Moi", recipe_id=1, recipe_name="Élixir de la mangouste",
        quantity=5, crafter_character_id=a.id, crafter_name="Alice Alchi", crafter_user_id=alice,
        reagents_text="10× Fleur de feu",
    ))
    assert order.id and db.get_order(order.id).status == "pending"
    assert allowed_actions(order, alice) == ["accept", "refuse"]
    assert allowed_actions(order, me) == ["cancel"]
    assert allowed_actions(order, bob) == []
    assert db.set_order_status(order.id, "accepted", ("pending",))
    assert not db.set_order_status(order.id, "refused", ("pending",))  # déjà acceptée : refus ignoré
    order = db.get_order(order.id)
    assert allowed_actions(order, alice) == ["done", "drop"]
    db.set_order_dm(order.id, 555, 666)
    assert db.get_order(order.id).crafter_dm_message_id == 666
    assert [o.id for o in db.user_orders(me)] == [order.id] and [o.id for o in db.user_orders(alice)] == [order.id]
    assert db.user_orders(bob) == []
    assert db.set_order_status(order.id, "done", ("accepted",))
    assert allowed_actions(db.get_order(order.id), me) == []
    db.close()


def test_orders_discord_rendering():
    """Embeds et boutons de commande ; le bouton qui ouvre le formulaire n'est pas « nettoyé »."""
    import asyncio
    import re
    from types import SimpleNamespace

    import discord

    from wowplanner.cogs.orders import OrderActionButton, order_embed, order_view, panel_embed
    from wowplanner.db import Order
    from wowplanner.ephemeral import EphemeralCleaner

    order = Order(
        guild_id=42, requester_id=1, requester_name="Moi", recipe_id=1, recipe_name="Élixir", quantity=2,
        crafter_character_id=5, crafter_name="Alice Alchi", crafter_user_id=2, reagents_text="4× Fleur", id=7,
    )

    async def scenario():
        embed = order_embed(order)
        assert "#7" in embed.title and "2× Élixir" in embed.title
        view = order_view(order, 2)
        ids = [item.custom_id for item in view.children]
        assert ids == ["wowplanner:order:accept:7", "wowplanner:order:refuse:7"]
        assert order_view(order, 99) is None
        assert re.fullmatch(OrderActionButton.__discord_ui_compiled_template__, "wowplanner:order:done:12")
        assert panel_embed().title

    asyncio.run(scenario())

    def inter(kind, custom_id=None):
        return SimpleNamespace(
            type=kind, guild_id=42, data={"custom_id": custom_id} if custom_id else {},
            message=SimpleNamespace(flags=SimpleNamespace(ephemeral=False)),
        )

    assert not EphemeralCleaner._creates_new_response(inter(discord.InteractionType.component, "wowplanner:order:new"))
    assert EphemeralCleaner._creates_new_response(inter(discord.InteractionType.component, "wowplanner:order:mine"))
    assert EphemeralCleaner._creates_new_response(inter(discord.InteractionType.modal_submit))


def test_item_tooltip_parse_and_site(tmp_path):
    """Infobulle de l'objet fabriqué (stats, effets) lue dans l'API et affichée sur le site."""
    import asyncio

    import aiohttp

    from wowplanner.armory import parse_item, parse_recipe
    from wowplanner.db import Database
    from wowplanner.web import WebSite

    item = parse_item({"preview_item": {
        "quality": {"type": "RARE"},
        "item_subclass": {"name": "Mailles"},
        "inventory_type": {"type": "CHEST", "name": "Torse"},
        "binding": {"name": "Lié quand équipé"},
        "armor": {"display": {"display_string": "Armure : 214"}},
        "stats": [{"display": {"display_string": "+14 Force"}}, {"display": {"display_string": "+6 Endurance"}}],
        "spells": [{"description": "Équipé : Augmente un truc <b>."}],
        "requirements": {"level": {"display_string": "Niveau 24 requis"}},
    }})
    assert item["quality"] == "RARE"
    assert item["lines"][0] == ["type", "Torse · Mailles"]
    assert ["stat", "+14 Force"] in item["lines"] and ["req", "Niveau 24 requis"] in item["lines"]
    elixir = parse_item({"preview_item": {"inventory_type": {"type": "NON_EQUIP", "name": "Hors équipement"},
                                          "item_subclass": {"name": "Élixirs"}}})
    assert elixir["lines"] == []
    enchant = parse_recipe({"name": "Enchantement de brassards", "description": "Endurance +2", "reagents": []})
    assert enchant.description == "Endurance +2" and enchant.crafted_item_id is None

    db = Database(tmp_path / "t.db")
    c = db.add_character(1, "Forge Ron", "guerrier", "nain")
    db.touch_member(42, 1)
    db.replace_professions(c.id, {"forge": 150, "enchantement": 50})
    db.replace_character_recipes(c.id, {"forge": [(1, "Breastplate")], "enchantement": [(2, "Bracer")]})
    db.set_recipe_details(1, "Cuirasse en argent lumineux", [(10, "Barre d'argent", 5)], 2870, 1.0, None, item)
    db.set_recipe_details(2, "Enchantement de brassards", [(1, "Granule", 6)], None, 1.0, "Endurance +2")
    assert db.recipes_missing_details() == []
    recipes = {r.id: r for r in db.guild_recipes(42)}
    assert recipes[1].item["quality"] == "RARE" and recipes[2].description == "Endurance +2"

    site = WebSite(db, lambda: 42)
    pages = {}

    async def scenario():
        await site.start("127.0.0.1", 0)
        port = next(iter(site._runner.sites))._server.sockets[0].getsockname()[1]
        async with aiohttp.ClientSession() as session:
            for path in ("/metier/forge", "/metier/enchantement", f"/perso/{c.id}"):
                async with session.get(f"http://127.0.0.1:{port}{path}") as resp:
                    pages[path] = await resp.text()
        await site.stop()

    asyncio.run(scenario())
    db.close()
    forge = pages["/metier/forge"]
    assert '<div class="stat">+14 Force</div>' in forge and "Armure : 214" in forge
    assert 'style="color:#4a9dff">Cuirasse' in forge  # couleur de qualité rare
    assert "&lt;b&gt;" in forge  # échappé
    assert '<div class="effect">Endurance +2</div>' in pages["/metier/enchantement"]
    assert "+14 Force" in pages[f"/perso/{c.id}"]


def test_family_plural_and_site_links():
    from wowplanner.config import public_url
    from wowplanner.recipes import plural

    assert plural("Rouleau") == "Rouleaux" and plural("Cristal") == "Cristaux" and plural("Feu") == "Feux"
    assert plural("Potion") == "Potions" and plural("Élixirs") == "Élixirs" and plural("Pneu") == "Pneus"
    assert plural("Bracelet") == "Bracelets" and plural("Festival") == "Festivals"

    assert public_url("", "wow.exemple.fr") == "https://wow.exemple.fr"
    assert public_url("https://wow.exemple.fr/", "autre.fr") == "https://wow.exemple.fr"
    assert public_url("wow.exemple.fr", "") == "https://wow.exemple.fr"
    assert public_url("", "") == ""


def test_character_look_on_site(tmp_path):
    """Niveau et images de l'armurerie : enregistrés à la synchro, affichés sur le site."""
    import asyncio

    import aiohttp

    from wowplanner.db import Database
    from wowplanner.web import WebSite

    db = Database(tmp_path / "t.db")
    c = db.add_character(1, "Hollie Tétine", "pretre", "humain")
    plain = db.add_character(1, "Sans Image", "mage", "gnome")
    db.touch_member(42, 1)
    render = "https://render.worldofwarcraft.com/forever-eu/character/98/1-main-raw.png"
    avatar = "https://render.worldofwarcraft.com/forever-eu/character/98/1-avatar.jpg"
    db.set_armory_look(c.id, 42, avatar, render)
    db.set_armory_look(c.id, 43, None, None)  # images absentes : on garde les anciennes
    c = db.get_character(c.id)
    assert (c.level, c.avatar_url, c.render_url) == (43, avatar, render)

    site = WebSite(db, lambda: 42)
    pages = {}

    async def scenario():
        await site.start("127.0.0.1", 0)
        port = next(iter(site._runner.sites))._server.sockets[0].getsockname()[1]
        async with aiohttp.ClientSession() as session:
            for path in ("/", f"/perso/{c.id}", f"/perso/{plain.id}"):
                async with session.get(f"http://127.0.0.1:{port}{path}") as resp:
                    pages[path] = await resp.text()
        await site.stop()

    asyncio.run(scenario())
    db.close()
    assert f'src="{avatar}"' in pages["/"] and 'class="avatar none"' in pages["/"]
    assert f'src="{render}"' in pages[f"/perso/{c.id}"] and "Niveau 43" in pages[f"/perso/{c.id}"]
    assert 'class="render"' not in pages[f"/perso/{plain.id}"]


def test_talents_parsing_and_site(tmp_path):
    """Arbres de talents (données de jeu) + talents du perso : grille, rangs, infobulles, positions aberrantes."""
    import asyncio

    import aiohttp

    from wowplanner.armory import ArmorySheet, parse_talent_index, parse_talent_tree
    from wowplanner.db import Database
    from wowplanner.web import WebSite

    href = "https://eu.api.blizzard.com/data/wow/talent-tree/1114/playable-specialization/78?namespace=x"
    assert parse_talent_index({"spec_talent_trees": [{"key": {"href": href}}, {"key": {}}]}) == [(1114, 78)]

    def node(nid, talent, name, row, col, ranks):
        return {"id": nid, "display_row": row, "display_col": col, "ranks": [
            {"rank": i + 1, "tooltip": {"talent": {"id": talent, "name": name},
                                        "spell_tooltip": {"spell": {"id": talent + 1}, "description": d,
                                                          "cast_time": "Passive"}}}
            for i, d in enumerate(ranks)]}

    tree = parse_talent_tree({
        "id": 1114, "name": "Magie de l'ombre", "playable_class": {"id": 5}, "playable_specialization": {"id": 78},
        "spec_talent_nodes": [
            node(1, 100, "Connexion spirituelle", 1, 14, ["Rang un", "Rang deux"]),
            node(2, 200, "Fouet mental", 3, 17, ["Fouette"]),
            node(3, 300, "Doublon perdu", 63, 170, ["?"]),
        ],
    })
    assert tree["class"] == "pretre" and [n["max"] for n in tree["nodes"]] == [2, 1, 1]

    sheet = ArmorySheet(profile={}, specializations={"specialization_groups": [{"is_active": True, "specializations": [
        {"specialization": {"id": 78, "name": "Magie de l'ombre"}, "spent_points": 2, "talents": [
            {"talent": {"id": 100, "name": "Connexion spirituelle"}, "talent_rank": 1,
             "spell_tooltip": {"description": "Rang un"}},
            {"talent": {"id": 300, "name": "Doublon perdu"}, "talent_rank": 1},
        ]}]}]})
    assert sheet.talents[0]["specs"][0]["talents"][0] == [100, "Connexion spirituelle", 1, "Rang un"]
    assert ArmorySheet(profile={}).talents is None

    db = Database(tmp_path / "t.db")
    db.replace_talent_trees([tree])
    c = db.add_character(1, "Hollie Tétine", "pretre", "humain")
    db.touch_member(42, 1)
    db.set_armory_look(c.id, 23, None, None, sheet.talents)
    db.set_armory_look(c.id, 23, None, None, None)  # talents illisibles : on garde les anciens
    assert db.get_character(c.id).talents == sheet.talents
    site = WebSite(db, lambda: 42)
    pages = {}

    async def scenario():
        await site.start("127.0.0.1", 0)
        port = next(iter(site._runner.sites))._server.sockets[0].getsockname()[1]
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://127.0.0.1:{port}/perso/{c.id}") as resp:
                pages["perso"] = await resp.text()
        await site.stop()

    asyncio.run(scenario())
    db.close()
    html = pages["perso"]
    assert "2 · Magie de l&#x27;ombre" in html
    assert 'class="tal on"' in html and "grid-row:1;grid-column:1" in html  # colonne 14 → 1re colonne
    assert 'class="tal off r"' in html and "grid-column:4" in html
    assert "Rang suivant :<span>Rang deux</span>" in html
    assert "Aussi : Doublon perdu 1/1" in html  # hors grille mais avec des points


def test_gear_stats_priorities_and_categories(tmp_path):
    """Équipement + stats de l'armurerie, spé devinée, stats prioritaires mises en avant, recettes par type."""
    import asyncio

    import aiohttp

    from wowplanner import gear
    from wowplanner.armory import icon_url, parse_item
    from wowplanner.db import Database, GuildRecipe
    from wowplanner.recipes import group_by_category
    from wowplanner.web import WebSite

    assert icon_url("https://render.worldofwarcraft.com/forever-eu/icons/56/1.jpg") == \
        "https://render.worldofwarcraft.com/eu/icons/56/1.jpg"
    equipment = gear.parse_equipment({"equipped_items": [
        {"slot": {"type": "SHOULDER"}, "item": {"id": 4314}, "name": "Épaulières", "quality": {"type": "UNCOMMON"},
         "level": {"value": 22}, "inventory_type": {"type": "SHOULDER", "name": "Epaule"},
         "stats": [{"display": {"display_string": "+4 Endurance"}},
                   {"display": {"display_string": "+4 Puissance des sorts"}}],
         "enchantments": [{"display_string": "+3 Intelligence"}]},
        {"slot": {"type": "MAIN_HAND"}, "item": {"id": 1}, "name": "Grosse hache", "inventory_type": {"type": "TWOHWEAPON"}},
    ]})
    assert equipment[0]["lines"][-1] == ["enchant", "+3 Intelligence"] and equipment[1]["two_hand"]
    stats = gear.parse_stats({"health": 515, "spell_hit": {"value": 17.0}, "intellect": {"base": 46, "effective": 52},
                              "power_type": {"name": "Mana"}, "power": 1174})
    assert stats["intellect"] == 52 and stats["power_name"] == "Mana"

    talents = lambda spec_id: [{"active": True, "specs": [{"spec_id": spec_id, "points": 11, "talents": []}]}]  # noqa: E731
    assert gear.detect_spec(talents(78), "heal", None) == "shadow"
    assert gear.detect_spec(talents(134), "tank", None) == "feral_bear"
    assert gear.detect_spec(talents(256), None, equipment) == "fury_2h"
    assert gear.detect_spec([], None, None) is None
    # Talents inconnus : spé supposée d'après la classe et le rôle ; toutes les spés de chaque classe ont leurs priorités
    assert gear.default_spec("guerrier", "tank") == "prot_warrior" and gear.default_spec("mage", None) == "frost"
    assert gear.default_spec("pretre", "heal") == "holy_priest" and gear.default_spec("chaman", "dps") == "elemental"
    assert all(x in gear.PRIORITIES for specs in gear.CLASS_SPECS.values() for x in specs)
    assert set(gear.SPEC_IDS.values()) <= set(gear.PRIORITIES)
    assert gear.line_tokens("+12 Puissance d’attaque") == ["attack_power"]
    assert gear.priority_ranks("shadow")["spell_hit"] == 1

    # Recettes classées d'après l'objet fabriqué
    def recipe(rid, name, item_class=None, slot=None, crafted=True, sub=None):
        info = {"class": item_class, "slot": slot, "slot_name": slot and slot.title(), "subclass_name": sub, "lines": []}
        return GuildRecipe(rid, name, [], [], crafted_item_id=rid if crafted else None,
                           item=info if item_class is not None else None)
    groups = dict(group_by_category([
        recipe(1, "Rouleau d'étoffe en lin", 7), recipe(2, "Potion de soins", 0, sub="Potions"),
        recipe(3, "Pantalon en lin", 4, "LEGS"), recipe(4, "Enchantement de bracelets - Endurance", crafted=False),
        recipe(5, "Truc inconnu"),
    ]))
    assert list(groups) == ["Composants d'artisanat", "Potions", "Armure : Legs", "Enchantement de bracelets", "Autres"]
    assert parse_item({"item_class": {"id": 7, "name": "Artisanat"}, "inventory_type": {"type": "NON_EQUIP"}})["class"] == 7

    db = Database(tmp_path / "t.db")
    c = db.add_character(1, "Hollie Tétine", "pretre", "humain", "heal")
    db.touch_member(42, 1)
    db.set_armory_look(c.id, 23, None, None, talents(78), stats, equipment)
    db.replace_professions(c.id, {"alchimie": 139, "cuisine": 57})
    db.set_item_icons({4314: "https://render.worldofwarcraft.com/forever-eu/icons/56/9.jpg"})
    site = WebSite(db, lambda: 42)
    pages = {}

    async def scenario():
        await site.start("127.0.0.1", 0)
        port = next(iter(site._runner.sites))._server.sockets[0].getsockname()[1]
        async with aiohttp.ClientSession() as session:
            for path in ("/", f"/perso/{c.id}"):
                async with session.get(f"http://127.0.0.1:{port}{path}") as resp:
                    pages[path] = await resp.text()
        await site.stop()

    asyncio.run(scenario())
    db.close()
    html = pages[f"/perso/{c.id}"]
    assert 'class="doll"' in html and "/eu/icons/56/9.jpg" in html
    assert '<option value="shadow" selected>Ombre</option>' in html and 'value="discipline"' in html
    assert 'class="srow capped"' in html and "17 % / 16 %" in html  # toucher au cap : barré, on passe à la suite
    assert 'class="stat prio" data-t="spell_power">+4 Puissance des sorts' in html and 'class="slot prio"' in html
    assert 'id="spec-data"' in html
    assert '<td class="prof"><small>Alchimie</small><b>139</b></td><td class="prof"><span class="none">—</span></td>' in pages["/"]
    assert '<td class="sec split"><b>57</b></td>' in pages["/"]  # cuisine, 1re colonne secondaire
    assert 'data-k="intellect" tabindex="0"' in html and "la réserve de mana" in html  # infobulles des stats


def test_web_auth_cookies(tmp_path):
    import time

    from wowplanner.webauth import load_secret, safe_next, sign, unsign

    secret = load_secret(tmp_path / "session_secret")
    assert load_secret(tmp_path / "session_secret") == secret  # gardée : les sessions survivent au redémarrage
    value = sign({"id": 1, "name": "Raug", "exp": time.time() + 60}, secret)
    assert unsign(value, secret)["name"] == "Raug"
    assert unsign(value, b"autre-cle") is None  # mauvaise clé
    sig = value.rsplit(".", 1)[1]
    forged = sign({"id": 2, "name": "Pirate", "exp": time.time() + 60}, b"x").rsplit(".", 1)[0]
    assert unsign(f"{forged}.{sig}", secret) is None  # contenu modifié
    assert unsign(sign({"id": 1, "exp": time.time() - 1}, secret), secret) is None  # expiré
    assert unsign("n'importe quoi", secret) is None and unsign(None, secret) is None
    assert safe_next("/perso/3?x=1") == "/perso/3?x=1"
    for bad in ("https://evil.fr", "//evil.fr", "/\\evil.fr", "", None):
        assert safe_next(bad) == "/"


def test_website_discord_login(tmp_path):
    """Site réservé aux membres : pages privées → connexion, donjons publics sans persos, refus des non-membres."""
    import asyncio
    import time
    from urllib.parse import parse_qs, urlparse

    import aiohttp

    from wowplanner.db import Database
    from wowplanner.web import WebSite
    from wowplanner.webauth import SESSION_COOKIE, DiscordOAuth, OAuthError, sign

    db = Database(tmp_path / "t.db")
    member_id, stranger_id = 123, 999
    hollie = db.add_character(member_id, "Hollie Tétine", "pretre", "humain", "heal")
    db.set_armory_look(hollie.id, 20, None, None, None, None, None)
    db.touch_member(42, member_id)

    class FakeOAuth(DiscordOAuth):
        async def fetch_user(self, code):
            if code == "bad":
                raise OAuthError("code expiré")
            return {"id": int(code), "name": f"Joueur{code}"}

    async def is_member(user_id):
        return user_id == member_id

    site = WebSite(db, lambda: 42)
    secret = b"k" * 32
    site.enable_auth(FakeOAuth(None, "1", "s", "https://wow.fr/auth/callback"), secret, is_member, secure_cookies=False)
    got = {}

    async def scenario():
        await site.start("127.0.0.1", 0)
        port = next(iter(site._runner.sites))._server.sockets[0].getsockname()[1]
        base = f"http://127.0.0.1:{port}"

        async def get(session, path):
            async with session.get(base + path, allow_redirects=False) as resp:
                return resp.status, await resp.text(), resp.headers.get("Location", "")

        async def login(session, code, next_path="/perso/1"):
            _, _, location = await get(session, f"/auth/login?next={next_path}")
            state = parse_qs(urlparse(location).query)["state"][0]
            got["authorize"] = location
            return await get(session, f"/auth/callback?code={code}&state={state}")

        jar = aiohttp.CookieJar(unsafe=True)  # cookies sur une adresse IP (127.0.0.1)
        async with aiohttp.ClientSession(cookie_jar=jar) as s:
            got["home_anon"] = await get(s, "/")
            got["dungeons_anon"] = await get(s, "/donjons")
            got["dungeon_anon"] = await get(s, "/donjon/the-deadmines")
            await get(s, "/auth/login?next=/")  # pose le cookie d'état…
            got["bad_state"] = await get(s, "/auth/callback?code=123&state=faux")
            got["callback"] = await login(s, str(member_id), "/metiers")
            got["home"] = await get(s, "/")
            got["dungeons"] = await get(s, "/donjons")
            got["logout"] = await get(s, "/auth/logout")
            got["home_after_logout"] = await get(s, "/")
        async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as s:
            got["stranger"] = await login(s, str(stranger_id))
            got["stranger_home"] = await get(s, "/")
            got["discord_down"] = await login(s, "bad")
        # Session d'un membre exclu depuis : la revérification quotidienne lui retire l'accès.
        old = int(time.time()) - 2 * 24 * 3600
        cookie = sign({"id": stranger_id, "name": "Ex", "chk": old, "exp": time.time() + 3600}, secret)
        async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True), cookies={SESSION_COOKIE: cookie}) as s:
            got["kicked"] = await get(s, "/")
        await site.stop()

    asyncio.run(scenario())
    db.close()

    status, text, _ = got["home_anon"]
    assert status == 401 and "Se connecter avec Discord" in text and "Hollie" not in text
    status, text, _ = got["dungeons_anon"]
    assert status == 200 and "Hollie" not in text and "Persos dans la tranche" not in text
    assert "connecte-toi avec Discord" in text
    status, text, _ = got["dungeon_anon"]
    assert status == 200 and "Hollie" not in text and "Réservé aux membres du serveur" in text
    assert "scope=identify" in got["authorize"] and "redirect_uri=https%3A%2F%2Fwow.fr%2Fauth%2Fcallback" in got["authorize"]
    assert got["bad_state"][0] == 400
    assert got["callback"][0] == 302 and got["callback"][2] == "/metiers"  # retour à la page demandée
    status, text, _ = got["home"]
    assert status == 200 and "Hollie Tétine" in text and f"Joueur{member_id}" in text and "Déconnexion" in text
    assert "Persos dans la tranche" in got["dungeons"][1]
    assert got["logout"][0] == 302 and got["home_after_logout"][0] == 401
    assert got["stranger"][0] == 403 and "réservé aux membres" in got["stranger"][1]
    assert got["stranger_home"][0] == 401  # pas de session pour un non-membre
    assert got["discord_down"][0] == 502
    assert got["kicked"][0] == 401


def test_website_guest_access(tmp_path):
    """Accès invité : lien caché (404 sans la bonne clé), mot de passe, lecture seule, révoqué si le mot de passe change."""
    import asyncio
    from types import SimpleNamespace

    import aiohttp

    from wowplanner.db import Database
    from wowplanner.web import WebSite
    from wowplanner.webauth import DiscordOAuth

    db = Database(tmp_path / "t.db")
    hollie = db.add_character(123, "Hollie Tétine", "pretre", "humain", "heal")
    db.set_armory_look(hollie.id, 20, None, None, None, None, None)
    db.touch_member(42, 123)

    async def is_member(user_id):
        raise AssertionError("pas de vérification Discord pour un invité")

    site = WebSite(db, lambda: 42)
    site.enable_auth(DiscordOAuth(None, "1", "s", "https://wow.fr/auth/callback"), b"k" * 32, is_member, secure_cookies=False)
    key = "cle-secrete-assez-longue"
    site.enable_guest(key, "motdepasse")
    got = {}

    async def scenario():
        await site.start("127.0.0.1", 0)
        port = next(iter(site._runner.sites))._server.sockets[0].getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as s:
            async def call(method, path, data=None):
                async with s.request(method, base + path, data=data, allow_redirects=False) as resp:
                    return resp.status, await resp.text(), resp.headers.get("Location", "")

            got["login_page"] = await call("GET", "/")
            got["wrong_key"] = await call("GET", "/auth/invite/mauvaise-cle-de-test")
            got["wrong_key_post"] = await call("POST", "/auth/invite/mauvaise-cle-de-test", {"password": "motdepasse"})
            got["form"] = await call("GET", f"/auth/invite/{key}")
            got["bad_pass"] = await call("POST", f"/auth/invite/{key}", {"password": "faux"})
            got["home_bad"] = await call("GET", "/")
            got["good_pass"] = await call("POST", f"/auth/invite/{key}", {"password": "motdepasse"})
            got["home"] = await call("GET", "/")
            got["dungeons"] = await call("GET", "/donjons")
            got["post"] = await call("POST", "/mes-persos", {"nom": "Intrus"})
            site.enable_guest(key, "nouveau")  # mot de passe changé : session invalidée
            got["revoked"] = await call("GET", "/")
            # Invité qui voit le site comme le joueur de « Hollie Tétine » (nom sans tenir compte de la casse).
            async def is_admin(user_id):
                return user_id == 123

            site.actions = SimpleNamespace(is_admin=is_admin)
            site.enable_guest(key, "autre", "hollie tétine")
            await call("POST", f"/auth/invite/{key}", {"password": "autre"})
            got["as_home"] = await call("GET", "/")
            got["as_post"] = await call("POST", f"/mes-persos/{hollie.id}/supprimer", {})
        await site.stop()

    asyncio.run(scenario())
    chars = [c.name for c in db.get_characters(0)]
    db.close()

    assert "/auth/invite" not in got["login_page"][1]  # le lien n'apparaît nulle part
    assert got["wrong_key"][0] == 404 and got["wrong_key_post"][0] == 404
    assert got["form"][0] == 200 and 'type="password"' in got["form"][1]
    assert got["bad_pass"][0] == 401 and "incorrect" in got["bad_pass"][1]
    assert got["home_bad"][0] == 401
    assert got["good_pass"][0] == 302 and got["good_pass"][2] == "/"
    status, text, _ = got["home"]
    assert status == 200 and "Hollie Tétine" in text and "Invité" in text and "lecture seule" in text
    assert "Administration" not in text
    assert "Persos dans la tranche" in got["dungeons"][1]
    assert got["post"][0] == 403 and "Lecture seule" in got["post"][1] and chars == []
    assert got["revoked"][0] == 401
    status, text, _ = got["as_home"]
    assert status == 200 and 'href="/admin"' in text and f'class="menu-char" href="/perso/{hollie.id}"' in text
    assert "lecture seule" in text
    assert got["as_post"][0] == 403


def test_help_page(tmp_path):
    """Page d'aide : publique, chapitre Administration réservé aux admins, captures toutes présentes et annotées."""
    import asyncio
    import re
    import time
    from pathlib import Path
    from types import SimpleNamespace

    import aiohttp

    from wowplanner import webhelp
    from wowplanner.db import Database
    from wowplanner.web import WebSite
    from wowplanner.webauth import SESSION_COOKIE, DiscordOAuth, sign

    # Chaque capture citée dans l'aide existe, avec sa taille et un repère pour chaque ligne de légende.
    source = Path(webhelp.__file__).read_text(encoding="utf-8")
    names = set(re.findall(r'shot\("([a-z0-9-]+)"', source))
    assert len(names) >= 20
    for name in names:
        assert name in webhelp.SHOTS, name
        assert (webhelp.SHOTS_DIR / f"{name}.webp").is_file(), name

    db = Database(tmp_path / "t.db")

    async def is_member(user_id):
        return True

    site = WebSite(db, lambda: 42)
    secret = b"k" * 32
    site.enable_auth(DiscordOAuth(None, "1", "s", "https://wow.fr/auth/callback"), secret, is_member, secure_cookies=False)

    async def is_admin(user_id):
        return user_id == 1

    site.enable_actions(SimpleNamespace(is_admin=is_admin))
    now = int(time.time())
    admin_cookie = sign({"id": 1, "name": "Modo", "chk": now, "exp": now + 3600}, secret)
    got = {}

    async def scenario():
        await site.start("127.0.0.1", 0)
        port = next(iter(site._runner.sites))._server.sockets[0].getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        async with aiohttp.ClientSession() as s:
            for key, path in (("anon", "/aide"), ("img", "/static/aide/sortie.webp"), ("bad", "/static/aide/..%2Fweb.py"),
                              ("png", "/static/aide/sortie.png"), ("login", "/"),
                              ("cgu", "/conditions"), ("privacy", "/confidentialite"),
                              ("logo", "/static/logo.svg"), ("favicon", "/favicon.ico")):
                async with s.get(base + path) as resp:
                    got[key] = (resp.status, await resp.read(), resp.headers.get("Content-Type", ""))
        async with aiohttp.ClientSession(cookies={SESSION_COOKIE: admin_cookie}) as s:
            async with s.get(base + "/aide") as resp:
                got["admin"] = (resp.status, await resp.text())
        await site.stop()

    asyncio.run(scenario())
    db.close()

    status, body, _ = got["anon"]
    text = body.decode()
    assert status == 200 and "Bien démarrer" in text and "Se connecter" in text and 'href="/aide" class="active"' in text
    assert 'data-ch="admin"' not in text and 'data-ch="sorties"' in text and 'data-ch="faq"' in text
    for figure in re.findall(r'<figure class="hshot">.*?</figure>', text, re.S):
        if "<img" in figure:  # autant de repères posés sur l'image que de lignes de légende
            assert figure.count('class="hmark"') == figure.count("<li data-n="), figure[:200]
    assert got["img"][0] == 200 and got["img"][2] == "image/webp" and got["img"][1][:4] == b"RIFF"
    assert got["bad"][0] == 404 and got["png"][0] == 404
    assert "/aide#debut-connexion" in got["login"][1].decode()  # lien d'aide sur la page de connexion
    # Conditions et confidentialité : publiques, liées en pied de page (y compris sur la page de connexion).
    for key, needle in (("cgu", "Droit applicable"), ("privacy", "Tes droits")):
        status, body, _ = got[key]
        assert status == 200 and needle in body.decode() and "Raugdae" in body.decode()
    for key in ("anon", "login", "cgu"):
        assert 'href="/conditions"' in got[key][1].decode() and 'href="/confidentialite"' in got[key][1].decode()
    # Logo (public, aussi en favicon), crédit ideapub en pied de page et dans l'aide.
    for key in ("logo", "favicon"):
        assert got[key][0] == 200 and got[key][2] == "image/svg+xml" and b"<svg" in got[key][1]
    for key in ("anon", "login", "cgu"):
        assert 'src="/static/logo.svg"' in got[key][1].decode() and "https://ideapub.ch/" in got[key][1].decode()
    assert 'class="help-about"' in got["anon"][1].decode()
    status, text = got["admin"]
    assert status == 200 and 'data-ch="admin"' in text and "La page Administration" in text


def test_sync_steps_without_armory(tmp_path):
    """Synchro : chaque étape donne une ligne de bilan, une étape en échec n'arrête pas les suivantes."""
    import asyncio
    from types import SimpleNamespace

    from wowplanner.cogs.sync import SyncCog

    class Registry:
        async def refresh(self, session):
            return 37

    class Stats:
        async def refresh(self):
            return False  # guide injoignable

    bot = SimpleNamespace(
        config=SimpleNamespace(timezone=PARIS, data_dir=tmp_path), instances=Registry(), http_session=None,
        db=None, get_cog=lambda name: Stats() if name == "StatSyncCog" else None,
    )
    cog = SyncCog(bot)
    assert cog._last_run() is None
    lines = asyncio.run(cog._run_steps(full=False))
    assert lines[0] == "✅ **Donjons et raids (wiki)** : 37 donjons et raids"
    assert lines[1].startswith("⚠️") and "anciennes priorités gardées" in lines[1]
    assert len(lines) == 6 and all(line.startswith("⏭️") for line in lines[2:])  # pas de clés Blizzard
    assert cog._last_run() is not None  # la synchro de nuit ne sera pas rattrapée au prochain démarrage


def test_stat_tooltips():
    from wowplanner.webcharacter import STAT_GROUPS, STAT_HELP, stat_tooltip

    # Chaque caractéristique affichée a son explication.
    assert {key for _, rows in STAT_GROUPS for key, _, _ in rows if key != "power"} <= set(STAT_HELP)
    mage = stat_tooltip("strength", "Force", "mage")
    assert mage.startswith('<div class="tt"><b>Force</b>') and "Mage : Inutile" in mage
    assert "note" not in stat_tooltip("strength", "Force", "voleur")  # pas de remarque pour cette classe
    assert "Inutile pour cette classe" in stat_tooltip("intellect", "Intelligence", "guerrier")
    assert "Se recharge vite" in stat_tooltip("power", "Énergie", "voleur")
    assert "Se gagne en frappant" in stat_tooltip("power", "Rage", "guerrier")
    assert "ressource" in stat_tooltip("power", "Focalisation", "chasseur")  # ressource inconnue : texte générique
    assert stat_tooltip("inconnue", "?", "mage") == ""


def test_dungeons_data_and_page(tmp_path):
    """Liste des donjons cohérente, et page qui place les persos du serveur dans les bonnes tranches."""
    import asyncio
    from datetime import date

    import aiohttp

    from wowplanner import dungeons
    from wowplanner.db import Database
    from wowplanner.web import WebSite

    names = [d.name for d in dungeons.DUNGEONS]
    assert len(names) == len(set(names)) == 35
    assert sum(d.new for d in dungeons.DUNGEONS) == 9
    for d in dungeons.DUNGEONS:
        assert dungeons.LEVEL_MIN <= d.low <= d.high <= dungeons.LEVEL_MAX
    lows = [d.low for d in dungeons.DUNGEONS]
    assert lows == sorted(lows)  # du plus bas au plus haut niveau
    krol = next(d for d in dungeons.DUNGEONS if d.english == "Krol'dok Stronghold")
    assert (krol.low, krol.high) == (40, 45)  # tranche corrigée par Blizzard
    ony = next(r for r in dungeons.RAIDS if r.english == "Onyxia's Lair")
    assert dungeons.raid_status(ony, date(2026, 12, 1)) == "Ouvre le 09/12/2026"
    assert dungeons.raid_status(ony, date(2026, 12, 9)) == "Ouvert"
    assert dungeons.raid_status(dungeons.RAIDS[-1]) == "À venir"

    db = Database(tmp_path / "t.db")
    low = db.add_character(1, "Petit Gnome", "mage", "gnome")
    top = db.add_character(2, "Grand Nain", "guerrier", "nain")
    db.add_character(3, "Sans Niveau", "pretre", "humain")
    for user in (1, 2, 3):
        db.touch_member(42, user)
    db.set_armory_look(low.id, 25, None, None)
    db.set_armory_look(top.id, 60, None, None)
    site = WebSite(db, lambda: 42)
    pages = {}

    async def scenario():
        await site.start("127.0.0.1", 0)
        port = next(iter(site._runner.sites))._server.sockets[0].getsockname()[1]
        async with aiohttp.ClientSession() as session:
            for key, path in (("d", "/donjons"), ("dm", "/donjon/the-deadmines"), ("hot", "/donjon/hall-of-thanes"),
                              ("ony", "/donjon/onyxias-lair"), ("brd", "/donjon/blackrock-depths"),
                              ("nope", "/donjon/inconnu")):
                async with session.get(f"http://127.0.0.1:{port}{path}") as resp:
                    pages[key] = (resp.status, await resp.text())
        await site.stop()

    asyncio.run(scenario())
    db.close()
    status, html = pages["d"]
    assert status == 200 and 'href="/donjons" class="active"' in html
    from html import unescape
    rows = {
        unescape(r.split("<b>")[1].split("<")[0]): r.split("</tr>")[0] for r in html.split('<td class="dname">')[1:]
    }
    assert 'href="/donjon/the-deadmines"' in html and 'data-href="/donjon/molten-core"' in html
    assert "Petit Gnome" in rows["Profondeurs de Brassenoire"] and "Grand Nain" not in rows["Profondeurs de Brassenoire"]
    assert "Grand Nain" in rows["Scholomance"] and "Petit Gnome" not in rows["Scholomance"]
    assert "Grand Nain" in rows["Repaire d'Onyxia"]  # raids : persos niveau 60
    assert "Sans Niveau" not in html
    assert '<option value="60">Grand Nain (60)</option>' in html
    assert 'data-low="40" data-high="45"' in html

    # Fiches : entrée et /way, parcours numéroté (optionnels à part), noms français de Blizzard, persos du bon niveau.
    status, dm = pages["dm"]
    assert status == 200 and "/way Marche de l&#x27;Ouest 42 72" in dm
    assert '<span class="dot">1</span><div class="sbody"><b>Rhahk’Zor</b>' in dm
    assert '<li class="step opt"><span class="dot">◇</span><div class="sbody"><b>Mineur' not in dm  # pas traduit au hasard
    assert "<b>Capitaine Vertepeau</b>" in dm and '<span class="en">Captain Greenskin</span>' in dm
    assert "deadmines-small.jpg" in dm and "warcrafttavern.com/forever/guides/the-deadmines/" in dm
    assert "Petit Gnome" in dm and "Grand Nain" not in dm
    hot = pages["hot"][1]
    assert "/way Forgefer 43.5 52" in hot and "Durgen Dirgehammer" in hot and "🏰" in hot  # pas de vignette Blizzard
    ony = pages["ony"][1]
    assert "Grand Nain" in ony and "onyxias-lair-small.jpg" in ony
    assert "Coordonnées exactes pas encore relevées" in pages["brd"][1]
    assert pages["nope"][0] == 404
    for slug in [d.slug for d in dungeons.DUNGEONS + dungeons.RAIDS]:
        from wowplanner.dungeon_guides import GUIDES
        assert slug in GUIDES and GUIDES[slug].bosses, slug  # chaque instance a sa fiche


def test_stat_priorities_from_guide(tmp_path):
    """Priorités relues dans le guide : lecture de la page, enregistrement, application ; page bizarre ignorée."""
    import copy

    from wowplanner import gear, statsource
    from wowplanner.db import Database

    row = '<tr><th scope="row" class="x">{}</th><td class="y">{}</td></tr>'
    page = "".join(row.format(*r) for r in [
        ("Shadow Priest", "Spell Power, Hit, Critical Strike"),
        ("Protection Paladin", "Stamina, Defense, Armor, Block chance and Block Value, Hit"),
        ("Protection Warrior", "Stamina, Defense, Dodge, Parry and Block, Block Value"),
        ("Combat Rogue", "Hit, Agility, dodge and parry reduction"),
        ("Arms Warrior", "Weapon damage per second, Hit, Strength, Weapon Skill"),
        ("Frost Mage", "Hit, Charisme magique"),  # stat inconnue : ligne ignorée
        ("Spells", "17%, which is 170 Hit Rating"),
        ("Melee and ranged attacks", "8%, which is 80 Hit Rating"),
    ])
    specs, caps = statsource.parse_page(page)
    assert specs["shadow"] == ["spell_power", "hit", "crit"]
    assert specs["prot_paladin"] == ["stamina", "defense", "armor", "avoidance", "block_value", "hit"]
    assert specs["prot_warrior"] == ["stamina", "defense", "avoidance", "block_value"]
    assert specs["combat"] == ["hit", "agility", "expertise"]
    assert specs["arms"] == ["weapon_dps", "hit", "strength", "weapon_skill"]
    assert "frost" not in specs and caps == {"spell": 17.0, "physical": 8.0}

    db = Database(tmp_path / "t.db")
    assert db.stat_priorities() == ({}, {}, None)
    db.set_stat_priorities(specs, caps)
    saved_specs, saved_caps, when = db.stat_priorities()
    db.close()
    assert saved_specs == specs and saved_caps == caps and when

    backup = (copy.deepcopy(gear.PRIORITIES), gear.SPELL_HIT_CAP, gear.PHYSICAL_HIT_CAP, gear.SOURCE_CHECKED_AT)
    try:
        gear.apply_overrides(saved_specs, saved_caps, when)
        assert gear.PRIORITIES["shadow"] == ("Ombre", "spell", ("spell_power", "hit", "crit"))
        assert gear.hit_cap("spell") == 17.0 and gear.hit_cap("melee") == 8.0
        assert gear.PRIORITIES["frost"][2][0] == "hit"  # pas relue : on garde l'ancienne
    finally:
        gear.PRIORITIES.clear()
        gear.PRIORITIES.update(backup[0])
        gear.SPELL_HIT_CAP, gear.PHYSICAL_HIT_CAP, gear.SOURCE_CHECKED_AT = backup[1:]


def test_db_web_fields(tmp_path):
    """Sorties et persos venus du site : pseudo de l'organisateur, origine du perso, rôle préféré modifiable."""
    from wowplanner.db import SOURCE_WEB, Database, Event

    db = Database(tmp_path / "t.db")
    assert db.last_event_channel(42) is None
    db.create_event(Event(1, 42, 7, 3, "Deadmines", "dungeon", None, 100, {"tank": 1, "heal": 1, "dps": 3},
                          created_at=10, creator_name="Raug"))
    db.create_event(Event(2, 42, 8, 3, "Deadmines", "dungeon", None, 100, {"tank": 1, "heal": 1, "dps": 3}, created_at=20))
    assert db.get_event(1).creator_name == "Raug" and db.get_event(2).creator_name is None
    assert db.last_event_channel(42) == 8
    web = db.add_character(1, "Grommash Hurlenfer", "guerrier", "orc", source=SOURCE_WEB)
    discord_one = db.add_character(1, "Aelys", "mage", "humain")
    loaded = {c.name: c for c in db.get_characters(1)}
    assert loaded["Grommash Hurlenfer"].source == SOURCE_WEB and loaded["Aelys"].source is None
    assert loaded["Aelys"].created_at and web.created_at
    db.set_preferred_role(discord_one.id, "dps")
    assert db.get_character(discord_one.id).preferred_role == "dps"
    db.set_preferred_role(discord_one.id, None)
    assert db.get_character(discord_one.id).preferred_role is None
    db.close()


def test_web_texts():
    from wowplanner.webmember import _date_fr, rich, when_text

    now = datetime(2026, 11, 18, 10, 0, tzinfo=PARIS)  # un mercredi
    at = lambda *a: int(datetime(*a, tzinfo=PARIS).timestamp())  # noqa: E731
    assert when_text(at(2026, 11, 18, 21, 0), PARIS, now) == "aujourd'hui à 21:00"
    assert when_text(at(2026, 11, 19, 20, 30), PARIS, now) == "demain à 20:30"
    assert when_text(at(2026, 11, 20, 21, 0), PARIS, now) == "vendredi 20 novembre à 21:00"
    assert when_text(at(2027, 1, 4, 21, 0), PARIS, now) == "lundi 4 janvier 2027 à 21:00"
    html_text = rich("✅ **Grom** <t:1800000000:F> <@123>\n<script>`/ajouter perso`", PARIS)
    assert "<b>Grom</b>" in html_text and "un joueur" in html_text and "&lt;t:" not in html_text
    assert "&lt;script&gt;" in html_text and "<br>" in html_text and "<code>/ajouter perso</code>" in html_text
    assert _date_fr("2026-12-24") == "24/12/2026" and _date_fr("demain") == "demain"


def test_member_pages_events_and_characters(tmp_path):
    """Sorties et « Mes persos » sur le site : affichage, jeton anti-falsification, messages après action."""
    import asyncio
    import re
    import time

    import aiohttp

    from wowplanner.db import Database, Event
    from wowplanner.web import WebSite
    from wowplanner.webauth import SESSION_COOKIE, DiscordOAuth, sign
    from wowplanner.webmember import ActionError

    db = Database(tmp_path / "t.db")
    me, organizer = 123, 456
    db.touch_member(42, me)
    hollie = db.add_character(me, "Hollie Tétine", "pretre", "humain", "heal")
    starts = int(time.time()) + 2 * 86400
    db.create_event(Event(111, 42, 7, organizer, "Les Mortemines", "dungeon", "18-24", starts,
                          {"tank": 1, "heal": 1, "dps": 3}, description="RDV <b>devant</b>", creator_name="Orga"))
    db.upsert_signup(111, organizer, "tank", "PseudoOrga", None)
    db.set_favorite(me, hollie.id)
    calls = []

    class Backend:
        timezone = PARIS
        armory_enabled = True
        sync_state = None

        async def is_admin(self, user_id):
            return user_id == me

        def last_sync(self):
            return None

        async def member_names(self, ids):
            return {i: f"Membre{i}" for i in ids}

        def match_instance(self, *names):
            return "Deadmines" if "The Deadmines" in names else None

        async def start_sync(self, user):
            calls.append(("sync", user.id))
            return "🔄 Synchro complète lancée."

        def event_channels(self):
            return [(7, "#sorties")]

        def instance_options(self):
            return [("Les Mortemines", "Les Mortemines (VC) — Donjon 5 joueurs")]

        async def can_manage(self, user_id, ev):
            return user_id == ev.creator_id

        async def signup(self, user, mid, role, character_id):
            calls.append(("signup", user.id, user.display_name, mid, role, character_id))
            if role == "dps":
                raise ActionError("Le rôle **DPS** est complet.")
            return f"✅ Inscrit en **Heal** pour **Les Mortemines** (<t:{starts}:F>)."

        async def create_event(self, user, channel, instance, date, heure, joueurs, tanks, heals, dps, description):
            calls.append(("create", channel, instance, date, heure, joueurs, tanks, heals, dps, description))
            return "✅ Sortie créée."

        async def armory_lookup(self, user_id, name):
            calls.append(("lookup", user_id, name))
            return {"status": "not_found", "name": name}

    class FakeOAuth(DiscordOAuth):
        async def fetch_user(self, code):
            raise AssertionError("pas utilisé")

    async def is_member(user_id):
        return True

    site = WebSite(db, lambda: 42)
    secret = b"k" * 32
    site.enable_auth(FakeOAuth(None, "1", "s", "https://wow.fr/auth/callback"), secret, is_member, secure_cookies=False)
    site.enable_actions(Backend())
    now = int(time.time())
    session = sign({"id": me, "name": "Raug", "chk": now, "exp": now + 3600}, secret)
    got = {}

    async def scenario():
        await site.start("127.0.0.1", 0)
        port = next(iter(site._runner.sites))._server.sockets[0].getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as anon:
            async with anon.get(base + "/sorties", allow_redirects=False) as resp:
                got["anon"] = resp.status
        jar = aiohttp.CookieJar(unsafe=True)
        async with aiohttp.ClientSession(cookie_jar=jar, cookies={SESSION_COOKIE: session}) as s:

            async def get(path):
                async with s.get(base + path, allow_redirects=False) as resp:
                    return resp.status, await resp.text()

            async def post(path, data, headers=None):
                async with s.post(base + path, data=data, headers=headers or {}, allow_redirects=False) as resp:
                    return resp.status, resp.headers.get("Location", "")

            got["page"] = await get("/sorties")
            token = re.search(r'name="csrf" value="([0-9a-f]+)"', got["page"][1]).group(1)
            got["signup"] = await post("/sortie/111/inscrire", {"csrf": token, "perso": str(hollie.id), "role": "heal"})
            got["after_signup"] = await get("/sorties")
            got["again"] = await get("/sorties")
            await post("/sortie/111/inscrire", {"csrf": token, "perso": str(hollie.id), "role": "dps"})
            got["refused"] = await get("/sorties")
            await post("/sortie/111/inscrire", {"perso": str(hollie.id), "role": "heal"})
            got["no_token"] = await get("/sorties")
            await post("/sortie/111/inscrire", {"csrf": token, "role": "heal"}, {"Origin": "https://evil.example"})
            got["cross_site"] = await get("/sorties")
            await post("/sorties", {"csrf": token, "salon": "7", "instance": "Les Mortemines", "date": "2026-12-24",
                                    "heure": "21:00", "tanks": "2", "joueurs": "", "description": "  "})
            await post("/sorties", {"csrf": token, "salon": "7", "instance": "X", "date": "2026-12-24",
                                    "heure": "21:00", "tanks": "deux"})
            got["bad_number"] = await get("/sorties")
            async with s.get(base + "/api/armurerie?nom=Gro") as resp:
                got["lookup"] = resp.status, await resp.json()
            got["mine"] = await get("/mes-persos")
            got["dungeon"] = await get("/donjon/the-deadmines")
            got["prefilled"] = await get("/sorties?instance=Deadmines")
            got["admin"] = await get("/admin")
            await post("/admin/sync", {"csrf": token})
            got["admin_after_sync"] = await get("/admin")
        async with aiohttp.ClientSession(
            cookie_jar=aiohttp.CookieJar(unsafe=True),
            cookies={SESSION_COOKIE: sign({"id": organizer, "name": "Orga", "chk": now, "exp": now + 3600}, secret)},
        ) as s:
            async with s.get(base + "/admin") as resp:
                got["admin_refused"] = resp.status, await resp.text()
        await site.stop()

    asyncio.run(scenario())
    db.close()

    assert got["anon"] == 401
    status, text = got["page"]
    assert status == 200 and "Les Mortemines" in text and "organisé par Orga" in text and "PseudoOrga" in text
    assert "RDV &lt;b&gt;devant&lt;/b&gt;" in text and "Hollie Tétine" in text and "Mes persos" in text
    assert "Annuler la sortie" not in text and 'action="/sorties"' in text  # pas organisateur ; formulaire de création
    assert got["signup"] == (302, "/sorties#s111")
    signups = [c for c in calls if c[0] == "signup"]
    assert signups[0] == ("signup", me, "Raug", 111, "heal", hollie.id)
    flash = got["after_signup"][1]
    assert 'class="flash"' in flash and "Inscrit en <b>Heal</b>" in flash and "&lt;t:" not in flash
    assert 'class="flash' not in got["again"][1]  # message montré une seule fois
    assert 'class="flash err"' in got["refused"][1] and "<b>DPS</b> est complet" in got["refused"][1]
    assert len(signups) == 2  # sans jeton, ou depuis un autre site : rien n'est fait
    assert "Formulaire expiré" in got["no_token"][1] and "Formulaire expiré" in got["cross_site"][1]
    creates = [c for c in calls if c[0] == "create"]
    assert creates == [("create", 7, "Les Mortemines", "24/12/2026", "21:00", None, 2, None, None, None)]
    assert "« Tanks » doit être un nombre" in got["bad_number"][1]
    assert got["lookup"] == (200, {"status": "not_found", "name": "Gro"})
    status, text = got["mine"]
    assert status == 200 and "Hollie Tétine" in text and 'data-armory="1"' in text and 'id="new-submit"' in text
    assert 'class="fav on"' in text  # perso préféré
    # Menu du compte : pseudo, persos (le préféré marqué), thème, administration pour un admin.
    page_text = got["page"][1]
    assert 'class="usermenu"' in page_text and "⭐ Hollie Tétine" in page_text and 'id="theme"' in page_text
    assert 'href="/admin"' in page_text and ">Guilde<" in page_text
    assert ">⭐ Hollie Tétine — Prêtre</option>" in page_text  # proposé en premier pour s'inscrire
    # Fiche de donjon → formulaire de sortie prérempli.
    assert "/sorties?instance=Deadmines#nouvelle" in got["dungeon"][1]
    prefilled = got["prefilled"][1]
    assert 'id="nouvelle" open' in prefilled and 'value="Deadmines"' in prefilled
    # Administration.
    status, text = got["admin"]
    assert status == 200 and "Persos des membres" in text and "Membre123" in text and "Hollie Tétine" in text
    assert ("sync", me) in calls and "Synchro complète lancée" in got["admin_after_sync"][1]
    assert got["admin_refused"][0] == 403 and "Gérer le serveur" in got["admin_refused"][1]


def test_web_bridge_rules(tmp_path):
    """Actions du site côté bot : perso vérifié dans l'armurerie, inscription avec un perso à soi et du bon rôle."""
    import asyncio
    import time
    from types import SimpleNamespace

    from wowplanner.armory import ArmorySheet
    from wowplanner.cogs.webbridge import WebBridge
    from wowplanner.db import SOURCE_WEB, Database, Event
    from wowplanner.instances import Instance
    from wowplanner.webmember import ActionError, WebUser

    db = Database(tmp_path / "t.db")
    profile = {"name": "Grommash", "surname": "Hurlenfer", "level": 34, "character_class": {"id": 1}, "race": {"id": 2}}

    class FakeArmory:
        available = True

        def __init__(self):
            self.lookups, self.applied = 0, []

        async def lookup(self, name):
            self.lookups += 1
            return (ArmorySheet(profile), True) if name == "Grommash Hurlenfer" else (None, False)

        async def fetch(self, name, max_age=0):
            return (ArmorySheet(profile), True) if name == "Grommash Hurlenfer" else (None, False)

        def apply(self, character, sheet):
            self.applied.append(character.name)

        async def fetch_item_icons(self, ids):
            pass

    class FakeEvents:
        def __init__(self):
            self.registered, self.refreshed = [], []

        async def register(self, message_id, user, role, character):
            self.registered.append((message_id, user.display_name, role, character.name if character else None))
            return True, f"✅ Inscrit en **{role}**."

        async def refresh_event(self, message_id):
            self.refreshed.append(message_id)

    class FakeMember:
        def __init__(self, user_id):
            self.display_name = f"M{user_id}"
            self.guild_permissions = SimpleNamespace(manage_guild=user_id == 1)  # Raug gère le serveur

    class FakeGuild:
        def get_member(self, user_id):
            return FakeMember(user_id)

    dms = []

    class FakeUser:
        def __init__(self, user_id):
            self.id = user_id

        async def send(self, text):
            dms.append((self.id, text))

    armory, events = FakeArmory(), FakeEvents()
    cogs = {"ArmoryCog": armory, "EventsCog": events}
    bot = SimpleNamespace(
        db=db, config=SimpleNamespace(timezone=PARIS, event_channel_ids=frozenset()), get_cog=cogs.get,
        website=SimpleNamespace(guild_id=lambda: 42), get_guild=lambda gid: FakeGuild(), get_user=FakeUser,
        instances=SimpleNamespace(all=[
            Instance("Deadmines", "DM/VC", "dungeon", 5), Instance("Temple of Atal'Hakkar (Sunken Temple)", "ST", "dungeon", 5),
        ]),
    )
    bridge = WebBridge(bot)
    raug, other = WebUser(1, "Raug"), WebUser(2, "Autre")

    async def scenario():
        assert (await bridge.armory_lookup(1, "Gr0mmash"))["status"] == "invalid"
        assert (await bridge.armory_lookup(1, "gro"))["status"] == "not_found"
        found = await bridge.armory_lookup(1, "grommash hurlenfer")
        assert found["status"] == "found" and found["class"] == "Guerrier" and found["race"] == "Orc"
        assert [r for r, _ in found["roles"]] == ["tank", "dps"] and found["level"] == 34
        await bridge.armory_lookup(1, "Grommash Hurlenfer")  # même perso : réponse gardée en mémoire
        assert armory.lookups == 2

        with pytest.raises(ActionError, match="ne peut pas être Heal"):
            await bridge.add_character(raug, "grommash hurlenfer", "heal")
        with pytest.raises(ActionError, match="introuvable"):
            await bridge.add_character(raug, "Inconnu Total", None)
        text = await bridge.add_character(raug, "grommash hurlenfer", "tank")
        assert "Grommash Hurlenfer" in text and "niveau 34" in text and armory.applied == ["Grommash Hurlenfer"]
        grom = db.get_characters(1)[0]
        assert (grom.wow_class, grom.race, grom.source, grom.preferred_role) == ("guerrier", "orc", SOURCE_WEB, "tank")
        assert db.guild_characters(42)[0].id == grom.id  # le joueur compte comme membre du serveur
        with pytest.raises(ActionError, match="déjà un perso"):
            await bridge.add_character(raug, "Grommash Hurlenfer", None)
        assert (await bridge.armory_lookup(1, "grommash hurlenfer"))["status"] == "duplicate"

        db.create_event(Event(9, 42, 7, 2, "Deadmines", "dungeon", None, int(time.time()) + 3600,
                              {"tank": 1, "heal": 1, "dps": 3}))
        db.create_event(Event(10, 99, 7, 2, "Ailleurs", "dungeon", None, int(time.time()) + 3600,
                              {"tank": 1, "heal": 1, "dps": 3}))
        with pytest.raises(ActionError, match="Choisis le perso"):
            await bridge.signup(raug, 9, "tank", None)
        with pytest.raises(ActionError, match="ne peut pas être Heal"):
            await bridge.signup(raug, 9, "heal", grom.id)
        with pytest.raises(ActionError, match="pas à toi"):
            await bridge.signup(other, 9, "tank", grom.id)
        with pytest.raises(ActionError, match="n'existe plus"):
            await bridge.signup(raug, 10, "tank", grom.id)  # sortie d'un autre serveur
        assert "Inscrit" in await bridge.signup(raug, 9, "tank", grom.id)
        assert events.registered == [(9, "Raug", "tank", "Grommash Hurlenfer")] and events.refreshed == [9]
        assert "plus de rôle préféré" in await bridge.set_role(raug, grom.id, None)
        assert db.get_character(grom.id).preferred_role is None
        assert "perso préféré" in await bridge.set_favorite(raug, grom.id) and db.get_character(grom.id).favorite
        assert "n'est plus" in await bridge.set_favorite(raug, grom.id) and not db.get_character(grom.id).favorite
        with pytest.raises(ActionError, match="pas à toi"):
            await bridge.delete_character(other, grom.id)  # Autre n'est pas admin
        db.upsert_signup(9, 1, "tank", "Raug", grom.id)
        assert "supprimé" in await bridge.delete_character(raug, grom.id)
        assert db.get_characters(1) == [] and events.refreshed == [9, 9] and dms == []

        # Administration : Raug (« Gérer le serveur ») gère les persos des autres membres, qui sont prévenus.
        assert await bridge.is_admin(1) and not await bridge.is_admin(2)
        with pytest.raises(ActionError, match="Gérer le serveur"):
            await bridge.add_character(other, "grommash hurlenfer", None, owner_id=1)
        text = await bridge.add_character(raug, "grommash hurlenfer", "dps", owner_id=2)
        assert "pour **M2**" in text and dms[-1][0] == 2 and "Raug" in dms[-1][1]
        theirs = db.get_characters(2)[0]
        assert "Tank" in await bridge.set_role(raug, theirs.id, "tank")
        with pytest.raises(ActionError, match="pas à toi"):
            await bridge.set_favorite(raug, theirs.id)  # le perso préféré reste le choix du joueur
        assert "supprimé" in await bridge.delete_character(raug, theirs.id)
        assert db.get_characters(2) == [] and "a supprimé ton perso" in dms[-1][1]

        # Fiche de donjon → nom dans la liste des instances.
        assert bridge.match_instance("The Deadmines", "Les Mortemines") == "Deadmines"
        assert bridge.match_instance("Sunken Temple", "Temple englouti") == "Temple of Atal'Hakkar (Sunken Temple)"
        assert bridge.match_instance("Nowhere") is None

    asyncio.run(scenario())
    db.close()


def test_nightly_cleanup_of_discord_characters(tmp_path):
    """Nettoyage de nuit : seuls les persos Discord introuvables depuis plus de 2 jours partent (joueur prévenu)."""
    import asyncio
    import time
    from types import SimpleNamespace

    from wowplanner.cogs.armory import FullSyncReport
    from wowplanner.cogs.sync import SyncCog
    from wowplanner.db import SOURCE_WEB, Database

    db = Database(tmp_path / "t.db")
    old = db.add_character(1, "Vieux Perso", "mage", "humain")
    web = db.add_character(1, "Site Perso", "mage", "humain", source=SOURCE_WEB)
    fresh = db.add_character(2, "Tout Neuf", "mage", "humain")
    db.add_character(3, "Bien Present", "mage", "humain")
    with db.conn:
        db.conn.execute("UPDATE characters SET created_at = ? WHERE id IN (?, ?)",
                        (int(time.time()) - 3 * 86400, old.id, web.id))
    by_id = {c.id: c for c in db.all_characters()}
    dms = []

    class FakeUser:
        def __init__(self, user_id):
            self.id = user_id

        async def send(self, text):
            dms.append((self.id, text))

    bot = SimpleNamespace(
        config=SimpleNamespace(timezone=PARIS, data_dir=tmp_path), db=db, get_cog=lambda name: None,
        get_user=FakeUser,
    )
    cog = SyncCog(bot)
    assert asyncio.run(cog._cleanup(False))[0] == "⏭️"  # persos pas relus : on ne touche à rien

    missing = [by_id[old.id], by_id[web.id], by_id[fresh.id]]
    cog._char_report = FullSyncReport(characters=4, found=0, not_found=3, unreachable=1, missing=missing)
    icon, text = asyncio.run(cog._cleanup(False))
    assert icon == "⚠️" and "annulé" in text and len(db.all_characters()) == 4  # personne trouvé : armurerie suspecte

    cog._char_report = FullSyncReport(characters=4, found=1, not_found=3, missing=missing)
    icon, text = asyncio.run(cog._cleanup(False))
    assert icon == "✅" and "1 perso(s)" in text and "Vieux Perso" in text
    assert sorted(c.name for c in db.all_characters()) == ["Bien Present", "Site Perso", "Tout Neuf"]
    assert len(dms) == 1 and dms[0][0] == 1 and "Vieux Perso" in dms[0][1]
    db.close()


def test_proficiency_rules():
    """Armures et armes par classe (Forever) : niveau 40 pour mailles/plaques, nouveautés Voleur et Druide."""
    from wowplanner import proficiency as p
    from wowplanner.armory import parse_item

    def armor(sub, req=None, name=None):
        return {"class": 4, "subclass": sub, "subclass_name": name, "slot": "CHEST", "req_level": req}

    def weapon(sub, req=None):
        return {"class": 2, "subclass": sub, "slot": "WEAPON", "req_level": req}

    assert p.usable_from("chasseur", armor(p.MAIL)) == 40 and p.usable_from("chasseur", armor(p.LEATHER, 12)) == 12
    assert p.usable_from("guerrier", armor(p.PLATE, 45)) == 45 and p.usable_from("guerrier", armor(p.MAIL)) == 1
    assert p.usable_from("mage", armor(p.LEATHER)) is None and p.usable_from("mage", armor(p.CLOTH)) == 1
    assert p.usable_from("pretre", armor(p.SHIELD)) is None and p.usable_from("chaman", armor(p.SHIELD)) == 1
    assert p.usable_from("voleur", weapon(p.AXE_1H)) == 1  # nouveau dans Forever
    assert p.usable_from("druide", weapon(p.POLEARM)) == 1  # nouveau dans Forever
    assert p.usable_from("pretre", weapon(p.SWORD_1H)) is None and p.usable_from("pretre", weapon(p.WAND, 20)) == 20
    assert p.usable_from("paladin", weapon(p.DAGGER)) is None and p.usable_from("guerrier", weapon(p.WAND)) is None
    # Objets lus avant l'identifiant du sous-type : reconnus par leur nom français.
    assert p.item_kind(armor(None, name="Mailles")) == (4, p.MAIL)
    assert p.item_kind({"class": 2, "subclass_name": "Haches à deux mains", "slot": "TWOHWEAPON"}) == (2, p.AXE_2H)
    assert p.item_kind({"class": 2, "subclass_name": "Armes d'hast", "slot": "TWOHWEAPON"}) == (2, p.POLEARM)
    assert p.item_kind({"class": 4, "subclass_name": "Divers", "slot": "FINGER"}) == (4, p.MISC)
    assert p.item_kind({"class": 0, "slot": "NON_EQUIP"}) is None  # consommable
    assert p.kind_label((2, p.DAGGER)) == "Dague"

    item = parse_item({
        "level": 35, "required_level": 30, "item_class": {"id": 4, "name": "Armure"},
        "item_subclass": {"id": 3, "name": "Mailles"},
        "preview_item": {"inventory_type": {"type": "CHEST", "name": "Torse"}, "level": {"value": 35},
                         "requirements": {"level": {"value": 30, "display_string": "Niveau 30 requis"}}},
    })
    assert (item["subclass"], item["req_level"], item["ilvl"], item["class"]) == (3, 30, 35, 4)


def test_crafted_gear_on_character_page(tmp_path):
    """Fiche perso : équipement fabricable par la guilde que le perso peut porter, comparé à ce qu'il porte."""
    from wowplanner.db import Crafter, GuildRecipe
    from wowplanner.webcharacter import crafted_gear_html
    from wowplanner.db import Character

    def recipe(rid, name, cls, sub, slot, req, ilvl, stats=()):
        item = {"class": cls, "subclass": sub, "slot": slot, "req_level": req, "ilvl": ilvl, "quality": "UNCOMMON",
                "lines": [["stat", s] for s in stats]}
        return GuildRecipe(rid, name, [], ["Forge Ron"], item=item)

    recipes = [
        recipe(1, "Cotte en mailles lourdes", 4, 3, "CHEST", 30, 35, ["+10 Force"]),
        recipe(2, "Plastron en thorium", 4, 4, "CHEST", 40, 45),
        recipe(3, "Jambières lointaines", 4, 4, "LEGS", 55, 60),
        recipe(4, "Robe de soirée", 4, 1, "ROBE", 20, 22, ["+5 Intelligence"]),
        recipe(5, "Dague de cuivre", 2, 15, "WEAPON", 8, 11),
        recipe(6, "Baguette magique", 2, 19, "RANGEDRIGHT", 10, 15),
        GuildRecipe(7, "Élixir de mangouste", [], ["Alice"], item={"class": 0, "slot": "NON_EQUIP", "lines": []}),
    ]
    warrior = Character(1, 10, "Grom", "guerrier", "orc", "dps", level=38,
                        equipment=[{"slot": "CHEST", "name": "Vieille cotte", "ilvl": 20, "lines": []}])
    crafters = {r.id: [Crafter(50 + r.id, "Forge Ron", 99, "guerrier")] for r in recipes}
    html_text = crafted_gear_html(warrior, recipes, crafters, 10, ["strength"])
    assert "Cotte en mailles lourdes" in html_text and "Plastron en thorium" in html_text  # plaques : bientôt (40)
    assert "Jambières lointaines" not in html_text  # niveau 55 : trop loin
    assert "Baguette magique" not in html_text and "Élixir" not in html_text  # pas pour un guerrier / pas équipable
    assert "Robe de soirée" in html_text and "Dague de cuivre" in html_text
    assert 'data-up="1"' in html_text and "Vieille cotte (20)" in html_text  # mieux que l'objet porté
    assert "à partir du niveau 40" in html_text and "/atelier?recette=1" in html_text
    assert 'class="stat prio"' in html_text  # Force : stat prioritaire de la spé
    assert html_text.index("Cotte en mailles lourdes") < html_text.index("Plastron en thorium")  # dispo d'abord
    mage = Character(2, 11, "Gnomy", "mage", "gnome", level=38)
    mage_html = crafted_gear_html(mage, recipes, crafters, None, [])
    assert "Robe de soirée" in mage_html and "Baguette magique" in mage_html and "Cotte" not in mage_html
    assert "Commander" not in mage_html  # visiteur non connecté
    assert crafted_gear_html(mage, recipes[:3], crafters, None, []) == ""


def test_orders_shared_with_site(tmp_path):
    """Atelier : commande préparée et suivie hors de Discord (site), mêmes règles qu'avec les boutons."""
    import asyncio
    from types import SimpleNamespace

    from wowplanner.cogs.orders import OrdersCog
    from wowplanner.db import Database

    db = Database(tmp_path / "t.db")
    me, alice = 1, 2
    a = db.add_character(alice, "Alice Alchi", "pretre", "humain")
    for user in (me, alice):
        db.touch_member(42, user)
    db.replace_character_recipes(a.id, {"alchimie": [(1, "Mongoose")]})
    db.set_recipe_details(1, "Élixir de la mangouste", [(2, "Fleur de feu", 100)], 900, 1.0)
    cog = OrdersCog(SimpleNamespace(db=db))
    sent = []

    async def fake_dm(user_id, content, embed, view):
        sent.append((user_id, content))
        return None

    cog._dm = fake_dm

    with pytest.raises(ValueError, match="Personne d'autre"):
        cog.build_order(42, alice, "Alice", 1, a.id, 1, None)  # sa propre recette
    with pytest.raises(ValueError, match="autre artisan"):
        cog.build_order(42, me, "Moi", 1, 999, 1, None)
    with pytest.raises(ValueError, match="quantité"):
        cog.build_order(42, me, "Moi", 1, a.id, 0, None)
    order = db.create_order(cog.build_order(42, me, "Moi", 1, a.id, 3, "merci"))
    assert order.crafter_user_id == alice and "6× Fleur de feu" in order.reagents_text

    async def scenario():
        updated, done = cog.transition(order, "accept")
        assert done and updated.status == "accepted"
        await cog.after_transition(updated, "accept")
        again, done_twice = cog.transition(order, "accept")  # double clic : un seul passe
        assert not done_twice and again.status == "accepted"

    asyncio.run(scenario())
    assert sent and sent[0][0] == me and "accepté" in sent[0][1]
    db.close()


def test_auction_aggregate_and_money():
    from wowplanner.auctions import aggregate, money_text, parse_search_item

    points = aggregate([
        {"item": {"id": 2589}, "quantity": 20, "unit_price": 30},
        {"item": {"id": 2589}, "quantity": 5, "unit_price": 25},
        {"item": {"id": 2589}, "quantity": 100, "unit_price": 40},
        {"item": {"id": 8499}, "quantity": 1, "buyout": 150000},
        {"item": {"id": 8499}, "quantity": 1, "buyout": 180000},
        {"item": {"id": 9999}, "quantity": 1, "bid": 500},  # enchère seule : ignorée
    ])
    linen = points[2589]
    assert (linen.min_price, linen.median_price, linen.quantity, linen.listings) == (25, 40, 125, 3)
    assert points[8499].min_price == 150000 and points[8499].listings == 2 and 9999 not in points
    assert money_text(150000) == "15 po" and money_text(1234567) == "123 po 45 pa 67 pc"
    assert money_text(10050) == "1 po 50 pc" and money_text(0) == "0 pc" and money_text(12345678) == "1 234 po 56 pa 78 pc"
    item = parse_search_item({
        "id": 8499, "name": {"fr_FR": "Minuscule jeune dragonnet cramoisi", "en_US": "Tiny Crimson Whelpling"},
        "quality": {"type": "COMMON"}, "item_class": {"id": 15, "name": {"fr_FR": "Divers"}},
        "item_subclass": {"id": 2, "name": {"fr_FR": "Familier"}}, "sell_price": 0, "is_stackable": False,
    })
    assert item.name == "Minuscule jeune dragonnet cramoisi" and item.search == "minuscule jeune dragonnet cramoisi"
    assert (item.class_name, item.subclass_name, item.stackable) == ("Divers", "Familier", False)
    assert parse_search_item({"id": 1}) is None


def test_auction_db_history_and_listing(tmp_path):
    from wowplanner.auctions import ItemRecord, PricePoint
    from wowplanner.db import Database

    db = Database(tmp_path / "t.db")
    db.upsert_ah_items([
        ItemRecord(2589, "Étoffe de lin", "COMMON", 7, "Artisanat", 5, "Tissu", 5, 0, 13, True),
        ItemRecord(8499, "Minuscule jeune dragonnet cramoisi", "COMMON", 15, "Divers", 2, "Familier", 30, 0, 0, False),
    ])
    day = 86400
    now = 1_800_000_000 // day * day + 12 * 3600
    db.store_ah_snapshot(now - day, {2589: PricePoint(40, 45, 100, 3)})
    db.store_ah_snapshot(now, {2589: PricePoint(30, 35, 200, 5), 8499: PricePoint(150000, 150000, 1, 1)})
    assert db.ah_snapshot_time() == now
    rows, total = db.ah_listing()
    assert total == 2 and [r["name"] for r in rows] == ["Étoffe de lin", "Minuscule jeune dragonnet cramoisi"]
    assert rows[0]["min_price_24h"] == 40  # variation sur 24 h
    assert [r["item_id"] for r in db.ah_listing(query="lin")[0]] == [2589]
    assert [r["item_id"] for r in db.ah_listing(query="dragonnet")[0]] == [8499]
    assert [r["item_id"] for r in db.ah_listing(class_id=15)[0]] == [8499]
    assert [r["item_id"] for r in db.ah_listing(sort="-prix")[0]] == [8499, 2589]
    assert db.ah_classes()[0][1] in ("Artisanat", "Divers")
    assert db.toggle_ah_favorite(7, 8499) is True and db.ah_favorite_ids(7) == {8499}
    assert [r["item_id"] for r in db.ah_listing(favorites_of=7)[0]] == [8499]
    assert db.toggle_ah_favorite(7, 8499) is False and db.ah_favorite_ids(7) == set()
    assert db.ah_item(2589)["min_price"] == 30 and db.ah_item(424242) is None

    # Historique : au-delà de 7 jours, un relevé par jour ; au-delà de 90 jours, plus rien.
    old = now - 10 * day
    for hour, price in ((1, 50), (2, 20), (3, 80)):
        db.store_ah_snapshot(old // day * day + hour * 3600, {2589: PricePoint(price, price + 10, 10, 1)})
    db.store_ah_snapshot(now - 100 * day, {2589: PricePoint(1, 1, 1, 1)})
    db.store_ah_snapshot(now, {2589: PricePoint(30, 35, 200, 5), 8499: PricePoint(150000, 150000, 1, 1)})
    db.compact_ah_prices(now)
    history = db.ah_history(2589, now - 200 * day)
    assert history[0][:3] == (old // day * day, 20, 60)  # plus bas prix du jour, médiane moyenne
    assert all(h[0] >= now - 90 * day for h in history) and len(history) == 3
    assert db.get_setting("x") is None
    db.set_setting("x", "1")
    assert db.get_setting("x") == "1"
    db.close()


def test_auction_cog_refresh(tmp_path):
    """Relevé : nouvelles données enregistrées une fois, catalogue des objets, objets inconnus complétés."""
    import asyncio
    from types import SimpleNamespace

    from wowplanner.cogs.auctions import AuctionCog
    from wowplanner.db import Database

    db = Database(tmp_path / "t.db")
    calls = {"auctions": 0, "search": 0, "item": 0}

    class FakeClient:
        locale = "fr_FR"

        async def auctions(self, ruleset, house, commodities):
            calls["auctions"] += 1
            if commodities:
                return {"auctions": [{"item": {"id": 2589}, "quantity": 20, "unit_price": 30}]}, 1_800_000_000.0
            return {"auctions": [{"item": {"id": 777}, "quantity": 1, "buyout": 5000}]}, 1_800_000_100.0

        async def search_items(self, from_id):
            calls["search"] += 1
            return [{"id": 2589, "name": {"fr_FR": "Étoffe de lin"}, "item_class": {"id": 7, "name": {"fr_FR": "Artisanat"}}}]

        async def item(self, item_id):
            calls["item"] += 1
            return {"id": item_id, "name": "Épée inconnue", "item_class": {"id": 2, "name": "Arme"}}

    class FakeArmory:
        available = True
        client = FakeClient()

        async def fetch_item_icons(self, ids):
            db.set_item_icons({i: f"https://render.worldofwarcraft.com/eu/icons/56/{i}.jpg" for i in ids})

    bot = SimpleNamespace(
        db=db, config=SimpleNamespace(auction_house_id=111, auction_ruleset=1),
        get_cog=lambda name: FakeArmory() if name == "ArmoryCog" else None,
    )
    cog = AuctionCog(bot)
    assert asyncio.run(cog.refresh()) == "2 objets relevés"
    assert db.ah_snapshot_time() == 1_800_000_100 // 3600 * 3600
    assert db.ah_item(777)["name"] == "Épée inconnue" and db.ah_item(2589)["name"] == "Étoffe de lin"
    assert db.ah_listing()[0][0]["icon"].startswith("https://")
    assert asyncio.run(cog.refresh()) == "pas de nouvelles données"
    assert calls["search"] == 1 and calls["item"] == 1  # catalogue lu une fois, objet inconnu demandé une fois
    db.close()


def test_auction_sales_estimate(tmp_path):
    """Ventes estimées : annonces sûres disparues et ventes partielles comptées, expirations possibles ignorées ;
    rangement par heure, couverture, passage à un par jour au-delà de 7 jours."""
    import asyncio
    from types import SimpleNamespace

    from wowplanner.auctions import estimate_sales, listing_state
    from wowplanner.cogs.auctions import AuctionCog
    from wowplanner.db import Database

    def a(auction_id, item, qty, left="LONG"):
        return {"id": auction_id, "item": {"id": item}, "quantity": qty, "time_left": left, "unit_price": 10}

    before = listing_state([a(5, 100, 20), a(1, 100, 3), a(2, 100, 4, "VERY_LONG"), a(3, 200, 1, "SHORT"),
                            a(4, 200, 7, "MEDIUM"), a(6, 300, 2)], 1000)
    after = listing_state([a(5, 100, 15), a(6, 300, 2), a(9, 100, 50)], 4600)
    # 100 : annonces 1 et 2 disparues (3 + 4) et 5 entamée (20 → 15) ; 200 : SHORT et MEDIUM ont pu expirer.
    assert estimate_sales(before, after) == {100: 12}
    assert list(before.ids) == [1, 2, 3, 4, 5, 6]

    db = Database(tmp_path / "t.db")
    day = 1_800_000_000 // 86400 * 86400
    db.store_ah_sales(day + 3600, {100: 12})
    db.store_ah_sales(day + 3600, {100: 3, 200: 1})  # deux relevés dans la même heure : additionnés
    db.store_ah_sales(day + 7200, {})  # heure relevée sans aucune vente
    assert db.ah_sales_history(100, 0) == [(day + 3600, 15, 1), (day + 7200, 0, 1)]
    assert db.ah_sales_history(300, 0) == [(day + 3600, 0, 1), (day + 7200, 0, 1)]
    db.compact_ah_sales(day + 8 * 86400)  # le jour passe à une ligne (somme, 2 heures couvertes)
    assert db.ah_sales_history(100, 0) == [(day, 15, 2)] and db.ah_sales_history(200, 0) == [(day, 1, 2)]
    db.compact_ah_sales(day + 8 * 86400)  # sans effet la deuxième fois
    assert db.ah_sales_history(100, 0) == [(day, 15, 2)]
    db.compact_ah_sales(day + 91 * 86400)
    assert db.ah_sales_history(100, 0) == []

    # Relevés successifs : une estimation à partir du deuxième, rangée dans l'heure du milieu de l'intervalle.
    t0 = 1_800_003_000.0
    snapshots = [(t0, [a(1, 100, 3), a(2, 100, 4)]), (t0 + 3600, [a(2, 100, 1)]), (t0 + 4 * 3600, [a(7, 100, 1)])]
    state = {"i": 0}

    class FakeClient:
        locale = "fr_FR"

        async def auctions(self, ruleset, house, commodities):
            ts, auctions = snapshots[state["i"]]
            return {"auctions": [] if commodities else auctions}, ts

        async def search_items(self, from_id):
            return []

        async def item(self, item_id):
            return {}

    class FakeArmory:
        available = True
        client = FakeClient()

        async def fetch_item_icons(self, ids):
            pass

    bot = SimpleNamespace(db=db, config=SimpleNamespace(auction_house_id=111, auction_ruleset=1),
                          get_cog=lambda name: FakeArmory() if name == "ArmoryCog" else None)
    cog = AuctionCog(bot)
    assert asyncio.run(cog.refresh()) == "1 objets relevés"
    state["i"] = 1
    assert asyncio.run(cog.refresh()) == "1 objets relevés, 6 ventes estimées"
    mid = int(t0 + 1800) // 3600 * 3600
    assert db.ah_sales_history(100, mid) == [(mid, 6, 1)]
    state["i"] = 2  # 3 h plus tard : des annonces LONG ont pu expirer, pas d'estimation
    asyncio.run(cog.refresh())
    assert len(db.ah_sales_history(100, mid)) == 1
    # Après un redémarrage sans fichier, le relevé déjà enregistré en base sert de point de départ.
    cog = AuctionCog(bot)
    assert asyncio.run(cog.refresh()) == "pas de nouvelles données" and cog._listing is not None

    # Avec data/ah_listing.bin : le relevé est relu au redémarrage, aucune heure perdue.
    from wowplanner.auctions import load_listing, save_listing
    assert load_listing(tmp_path / "absent.bin") is None
    (tmp_path / "abime.bin").write_bytes(b"AHL1" + b"\0" * 5)
    assert load_listing(tmp_path / "abime.bin") is None
    save_listing(before, tmp_path / "copie.bin")
    copy = load_listing(tmp_path / "copie.bin")
    assert copy == before and estimate_sales(copy, after) == {100: 12}

    bot.config.data_dir = tmp_path
    snapshots[:] = [(t0 + 10 * 3600, [a(1, 100, 3), a(2, 100, 4)]), (t0 + 11 * 3600, [a(2, 100, 4)])]
    state["i"] = 0
    asyncio.run(AuctionCog(bot).refresh())
    assert (tmp_path / "ah_listing.bin").is_file()
    state["i"] = 1
    restarted = AuctionCog(bot)  # nouveau démarrage : relit le fichier
    assert restarted._listing is not None and restarted._listing.ts == t0 + 10 * 3600
    assert asyncio.run(restarted.refresh()) == "1 objets relevés, 3 ventes estimées"
    db.close()


def test_auction_pages(tmp_path):
    """Page Hôtel des ventes : liste, recherche, favoris (JSON), fiche avec courbe, historique pour le survol."""
    import asyncio
    import re
    import time

    import aiohttp

    from wowplanner.auctions import ItemRecord, PricePoint
    from wowplanner.db import Database
    from wowplanner.web import WebSite
    from wowplanner.webauth import SESSION_COOKIE, DiscordOAuth, sign

    db = Database(tmp_path / "t.db")
    db.upsert_ah_items([
        ItemRecord(2589, "Étoffe de lin", "COMMON", 7, "Artisanat", 5, "Tissu", 5, 0, 13, True),
        ItemRecord(8499, "Minuscule jeune dragonnet cramoisi", "COMMON", 15, "Divers", 2, "Familier", 30, 0, 0, False),
    ])
    now = int(time.time()) // 3600 * 3600
    for h in range(48, -1, -6):
        db.store_ah_snapshot(now - h * 3600, {2589: PricePoint(30 + h, 40 + h, 200, 5),
                                              8499: PricePoint(150000, 150000, 1, 1)})
    for h in range(1, 30):  # ventes estimées sur 29 heures : de quoi tracer la demande selon l'heure
        db.store_ah_sales(now - h * 3600, {2589: 10 + h % 5})

    class FakeOAuth(DiscordOAuth):
        async def fetch_user(self, code):
            raise AssertionError("pas utilisé")

    async def is_member(user_id):
        return True

    site = WebSite(db, lambda: 42)
    secret = b"k" * 32
    site.enable_auth(FakeOAuth(None, "1", "s", "https://wow.fr/auth/callback"), secret, is_member, secure_cookies=False)
    site.auction_house = 111
    stamp = int(time.time())
    session = sign({"id": 5, "name": "Raug", "chk": stamp, "exp": stamp + 3600}, secret)
    got = {}

    async def scenario():
        await site.start("127.0.0.1", 0)
        port = next(iter(site._runner.sites))._server.sockets[0].getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True), cookies={SESSION_COOKIE: session}) as s:
            async def get(path):
                async with s.get(base + path, allow_redirects=False) as resp:
                    return resp.status, await resp.text()
            got["list"] = await get("/hdv")
            got["search"] = await get("/hdv?q=dragonnet")
            token = re.search(r'name="csrf" value="([0-9a-f]+)"', got["list"][1]).group(1)
            async with s.post(base + "/hdv/favori/8499", data={"csrf": token},
                              headers={"Accept": "application/json"}) as resp:
                got["fav"] = resp.status, await resp.json()
            async with s.post(base + "/hdv/favori/2589", data={}, headers={"Accept": "application/json"}) as resp:
                got["fav_no_token"] = resp.status
            got["favs"] = await get("/hdv?favoris=1")
            got["item"] = await get("/hdv/objet/2589?periode=3j")
            got["unknown"] = await get("/hdv/objet/424242")
            async with s.get(base + "/api/hdv/2589/historique?jours=7") as resp:
                got["api"] = await resp.json()
        await site.stop()

    asyncio.run(scenario())
    db.close()

    status, text = got["list"]
    assert status == 200 and "Étoffe de lin" in text and "dragonnet cramoisi" in text and "n° 111" in text
    assert '<td class="coin mg"><a class="price" href="/hdv/objet/8499" data-item="8499">15</a></td>' in text  # 15 po
    assert 'data-item="8499"><span class="zero">0</span></a></td>' in text  # 15 po 0 pa 0 pc : zéros estompés
    assert '<th class="coin mg">po</th>' in text
    assert 'data-item="2589"' in text and "▼" in text  # moins cher qu'il y a 24 h
    assert "Étoffe de lin" not in got["search"][1] and "dragonnet" in got["search"][1]
    assert got["fav"] == (200, {"favorite": True}) and got["fav_no_token"] == 403
    assert "dragonnet" in got["favs"][1] and "Étoffe de lin" not in got["favs"][1]
    status, text = got["item"]
    assert status == 200 and 'class="price-chart"' in text and "Cours sur 3 jours" in text
    data = re.search(r'<script type="application/json" class="chart-data">(.*?)</script>', text, re.S).group(1)
    import json
    assert len(json.loads(data)["points"]) == 9  # 72 h, un relevé toutes les 6 h (le plus ancien : 48 h)
    assert text.count('<rect class="vol"') == 29 and len(json.loads(data)["sales"]) == 29  # ventes dans la courbe
    assert 'class="price-chart sales-chart"' not in text and text.count('<g class="bar') == 24
    assert 'class="price-chart hours-chart"' in text and "Quand ça se vend" in text and "Vendus (24 h)" in text
    assert got["unknown"][0] == 404
    assert got["api"]["name"] == "Étoffe de lin" and len(got["api"]["points"]) == 9


def test_profit_computation():
    """Rentabilité : vente nette (commission 5 %), composants HdV ou marchand, recettes sans prix en dernier."""
    from wowplanner.db import GuildRecipe
    from wowplanner.profit import gathering_rows, recipe_profits, reagent_price

    def item(min_price=None, sell=None, purchase=None, qty=1):
        return {"min_price": min_price, "sell_price": sell, "purchase_price": purchase, "purchase_quantity": qty,
                "quantity": 12 if min_price else None}

    items = {
        929: item(1000, sell=50), 2447: item(200, purchase=40), 3371: item(500, purchase=20),
        4596: item(None, sell=30), 5555: item(3000), 2320: item(None, purchase=100, qty=5),
    }
    assert reagent_price(3371, items) == (20, "marchand")  # vendu par les marchands : moins cher qu'à l'HdV
    assert reagent_price(2447, items) == (200, "hdv")  # pas vendu par les marchands : prix de l'HdV
    assert reagent_price(2320, items) == (20, "marchand")  # 100 pc les 5
    assert reagent_price(4596, items) == (None, None) and reagent_price(None, items) == (None, None)
    recipes = [
        GuildRecipe(1, "Potion de soins mineure", [(1, "Pacifique", 2447), (1, "Fiole vide", 3371)], [], 929, 1.0),
        GuildRecipe(2, "Enchantement de brassards", [(1, "Poussière", 10940)], [], None),
        GuildRecipe(3, "Potion hors vente", [(1, "Pacifique", 2447)], [], 4596, 1.0),
        GuildRecipe(4, "Objet cher", [(2, "Inconnu", 999)], [], 5555, 2.0),
    ]
    results, without_item = recipe_profits(recipes, items)
    assert without_item == 1 and [r.recipe_id for r in results] == [1, 4, 3]
    potion = results[0]
    assert (potion.revenue, potion.cost, potion.profit, potion.vendor_value) == (950, 220, 730, 50)
    assert round(potion.margin) == 332 and potion.available == 12
    expensive = results[1]
    assert expensive.revenue == 5700 and expensive.missing == 1 and expensive.profit is None  # 2 × 3000 × 0,95
    assert results[2].revenue is None and results[2].vendor_value == 30

    from wowplanner.profit import gathered_value

    herb = gathered_value({"min_price": 200, "sell_price": 10})
    assert (herb.net, herb.vendor, herb.gain, round(herb.margin)) == (190, 10, 180, 1800)
    cheap = gathered_value({"min_price": 10, "sell_price": 25})  # mieux vaut le marchand
    assert cheap.gain == -16 and round(cheap.margin) == -64
    assert gathered_value({"min_price": None, "sell_price": 25}).gain is None
    assert gathered_value({"min_price": 100, "sell_price": 0}).margin is None  # pas de prix marchand : pas de %

    from wowplanner.profit import gather_requirement, out_of_reach

    assert gather_requirement(8838) == ("herboristerie", 230) and gather_requirement(929) is None
    assert out_of_reach(8838, {"herboristerie": 120}) and not out_of_reach(8838, {"herboristerie": 230})
    assert out_of_reach(2770, {"herboristerie": 300})  # minerai sans le minage
    assert not out_of_reach(929, {}) and not out_of_reach(8838, {"herboristerie": None})  # inconnu : jamais exclu

    rows = [{"item_id": 3356, "min_price": 900}, {"item_id": 2447, "min_price": 200}, {"item_id": 777777, "min_price": 50}]
    ordered = gathering_rows(rows, {2447: 1, 3356: 125}, 100)
    assert [(r[0]["item_id"], r[1], r[2]) for r in ordered] == [(2447, 1, True), (777777, None, True), (3356, 125, False)]


def test_craft_plan():
    """Calculatrice : la recette la plus rentable d'abord, puis la suivante avec le reste, le reste vendu brut."""
    from wowplanner.db import GuildRecipe
    from wowplanner.profit import craft_plan, raw_unit

    def item(min_price=None, sell=0, purchase=None):
        return {"min_price": min_price, "sell_price": sell, "purchase_price": purchase, "purchase_quantity": 1}

    items = {
        2447: item(100, sell=10), 785: item(300), 3371: item(purchase=20),  # pacifique, mage royal, fiole (marchand)
        118: item(1000), 858: item(400), 999: item(50, sell=40),  # potions, objet sans intérêt
    }
    assert raw_unit(items[2447]) == 95 and raw_unit(items[999]) == 47 and raw_unit(None) == 0
    assert raw_unit(item(10, sell=25)) == 25  # mieux vaut le marchand
    recipes = [
        GuildRecipe(1, "Potion A", [(1, "Pacifique", 2447), (1, "Mage royal", 785), (1, "Fiole", 3371)], [], 118, 1.0),
        GuildRecipe(2, "Potion B", [(2, "Pacifique", 2447), (1, "Fiole", 3371)], [], 858, 1.0),
        GuildRecipe(3, "Bricole", [(1, "Pacifique", 2447)], [], 999, 1.0),
        GuildRecipe(4, "Que des fioles", [(1, "Fiole", 3371)], [], 118, 1.0),  # rien du stock : ignorée
    ]
    plan = craft_plan({2447: 5, 785: 2, 4242: 3}, recipes, items)
    assert plan.raw_total == 5 * 95 + 2 * 285 and plan.unpriced == {4242}
    assert [(s.name, s.crafts) for s in plan.steps] == [("Potion A", 2), ("Potion B", 1)]
    a, b = plan.steps
    assert (a.product_value, a.buy_cost, a.used_value, a.gain) == (1900, 40, 760, 1100)
    assert (b.product_value, b.buy_cost, b.used_value, b.gain) == (380, 20, 190, 170)
    assert plan.leftovers == {2447: 1, 4242: 3} and plan.leftover_value == 95
    assert plan.total == 1860 + 360 + 95 and plan.gain == 1270
    assert [(s.name, s.crafts, s.gain) for s in plan.options] == [
        ("Potion A", 2, 1100), ("Potion B", 2, 340), ("Bricole", 5, -240),
    ]
    nothing = craft_plan({785: 3}, recipes, items)  # sans pacifique, aucune recette possible
    assert nothing.steps == [] and nothing.options == [] and nothing.gain == 0


def test_profit_page(tmp_path):
    import asyncio
    import time

    import aiohttp

    from wowplanner.auctions import ItemRecord, PricePoint
    from wowplanner.db import Database
    from wowplanner.web import WebSite
    from wowplanner.webauth import SESSION_COOKIE, DiscordOAuth, sign

    db = Database(tmp_path / "t.db")
    me = 5
    db.touch_member(42, me)
    hollie = db.add_character(me, "Hollie Tétine", "pretre", "humain", "heal")
    db.replace_professions(hollie.id, {"alchimie": 150, "herboristerie": 120})
    db.replace_character_recipes(hollie.id, {"alchimie": [(1, "Minor Healing Potion"), (2, "Swiftness Potion")]})
    db.set_recipe_details(1, "Potion de soins mineure", [(1, "Pacifique", 2447), (1, "Fiole vide", 3371)], 929, 1.0)
    db.set_recipe_details(2, "Potion de rapidité", [(1, "Chardonnier", 2452), (1, "Soleillette", 8838)], 2459, 1.0)
    db.upsert_ah_items([
        ItemRecord(929, "Potion de soins mineure", "COMMON", 0, "Consommable", 1, "Potion", 5, 1, 50, True, 200),
        ItemRecord(2447, "Pacifique", "COMMON", 7, "Artisanat", 9, "Herbes", 5, 0, 10, True, 40),
        ItemRecord(3356, "Sang-royal", "COMMON", 7, "Artisanat", 9, "Herbes", 25, 0, 30, True, 120),
        ItemRecord(3371, "Fiole vide", "COMMON", 7, "Artisanat", 11, "Autre", 1, 0, 1, True, 20),
        ItemRecord(2452, "Chardonnier", "COMMON", 7, "Artisanat", 9, "Herbes", 15, 0, 15, True, 60),
        ItemRecord(8838, "Soleillette", "COMMON", 7, "Artisanat", 9, "Herbes", 46, 0, 60, True, 240),
    ])
    db.store_ah_snapshot(int(time.time()) // 3600 * 3600, {
        929: PricePoint(1000, 1100, 12, 3), 2447: PricePoint(200, 210, 50, 4), 3356: PricePoint(900, 950, 8, 2),
    })

    class FakeOAuth(DiscordOAuth):
        async def fetch_user(self, code):
            raise AssertionError("pas utilisé")

    async def is_member(user_id):
        return True

    site = WebSite(db, lambda: 42)
    secret = b"k" * 32
    site.enable_auth(FakeOAuth(None, "1", "s", "https://wow.fr/auth/callback"), secret, is_member, secure_cookies=False)
    site.auction_house = 111
    stamp = int(time.time())
    session = sign({"id": me, "name": "Raug", "chk": stamp, "exp": stamp + 3600}, secret)
    got = {}

    async def scenario():
        await site.start("127.0.0.1", 0)
        port = next(iter(site._runner.sites))._server.sockets[0].getsockname()[1]
        async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True), cookies={SESSION_COOKIE: session}) as s:
            async with s.get(f"http://127.0.0.1:{port}/rentabilite") as resp:
                got["page"] = resp.status, await resp.text()
            async with s.get(f"http://127.0.0.1:{port}/calculatrice") as resp:
                got["calc_empty"] = resp.status, await resp.text()
            async with s.get(f"http://127.0.0.1:{port}/calculatrice?perso={hollie.id}&q2447=10") as resp:
                got["calc"] = resp.status, await resp.text()
        await site.stop()

    asyncio.run(scenario())
    db.close()
    status, text = got["page"]
    assert status == 200 and "Hollie Tétine" in text and "Alchimie" in text and "Herboristerie" in text
    assert "Potion de soins mineure" in text and "+ 7 pa 30 pc" in text  # 950 − (200 + 20)
    assert "(marchand)" in text and "(HdV)" in text  # fiole au prix du marchand, pacifique au prix de l'HdV
    assert 'class="later"' in text and "Sang-royal" in text  # niveau 125 : pas encore récoltable (120)
    assert text.index("Pacifique</span></span></a>") < text.index("Sang-royal</span></span></a>")
    assert 'href="/rentabilite"' in text  # lien dans le menu du compte
    # Récolte : Pacifique à 200 pc → 190 pc nets, revendu 10 pc au marchand → 180 pc de plus, marge de 1800 %.
    assert "+ 1 pa 80 pc" in text and "+1800 %" in text and "Gain vs marchand" in text
    assert 'href="/calculatrice"' in text
    # Un onglet par métier, avec le niveau ; récolte et fabrication dans le panneau du métier.
    assert '<button type="button" data-tab="alchimie">Alchimie<span class="n">150</span></button>' in text
    assert '<div data-panel="herboristerie">' in text and text.index('data-panel="alchimie"') < text.index("fabrication")

    # Calculatrice : stock à saisir = herbes récoltables à son niveau (pas le Sang-royal, niveau 125).
    status, text = got["calc_empty"]
    assert status == 200 and 'name="q2447"' in text and 'name="q3356"' not in text and "Résultat" not in text
    # Composants des recettes : Soleillette (Herboristerie 230) hors de portée à 120, Chardonnier obtenu en bonus.
    assert 'data-out="1" data-name="soleillette"' in text and 'data-out="0" data-name="chardonnier"' in text
    assert "Hors de ta compétence : Herboristerie 230 requis" in text and "Masquer ce qui est hors de ma compétence" in text
    assert 'class="bonus"' in text and "Chance de loot" in text
    # 10 Pacifique : vendus bruts 10 × 190 pc = 19 pa ; en potions : 10 × (950 − 20 de fiole) = 93 pa → 74 pa de plus.
    status, text = got["calc"]
    assert status == 200 and "Fabriquer rapporte <b>74 pa</b>" in text and "+ 74 pa" in text
    assert 'value="10"' in text and "Chaque recette seule" in text
    # Saisie en tableau : prix net, meilleure vente, valeur brute de la ligne et total (10 × 190 pc).
    assert 'data-unit="190"' in text and '<td class="best"><span class="chan hdv">HdV</span></td>' in text
    assert '<td class="num value">19 pa</td>' in text and '<td class="num calc-total">19 pa</td>' in text
    # Groupes repliables et filtre par catégorie.
    assert '<tr class="grp" data-group="0">' in text and 'aria-expanded="true"><span class="arrow">▾</span> Herboristerie : herbes' in text
    assert '<option value="0">Herboristerie : herbes (1)</option>' in text
    # Résultat : où l'argent est gagné ou dépensé (potions vendues à l'HdV, fiole achetée au marchand).
    assert '+ 95 pa <span class="chan hdv">HdV</span>' in text and '− 2 pa <span class="chan marchand">Marchand</span>' in text
