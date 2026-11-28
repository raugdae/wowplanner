"""Quêtes de donjon : liste Blizzard, chasse au trésor (relevés de l'addon fusionnés par le site), Data.lua, fenêtre
de l'addon (lupa), API et synchro."""
import asyncio
import json
import time

import pytest

from test_addon import client, lua_to_python, run_addon, to_lua
from wowplanner.quests import parse_hunt

QUEST_API = r"""
LEVEL = 20
function UnitLevel() return LEVEL end
function UnitFactionGroup() return "Alliance" end
NPC = nil  -- PNJ en face du joueur : { guid, name }
function UnitExists(unit) return unit == "npc" and NPC ~= nil end
function UnitGUID(unit) if unit == "player" then return "Player-1-0001" end return NPC and NPC.guid end
function UnitName(unit) if unit == "npc" then return NPC and NPC.name end return "Elwyn" end
GOSSIP = {}
C_GossipInfo = { GetAvailableQuests = function() return GOSSIP end }
DETAIL = nil
function GetQuestID() return DETAIL end
function GetTitleText() return "Titre " .. tostring(DETAIL) end
C_Map = {
  GetBestMapForUnit = function() return 1436 end,
  GetPlayerMapPosition = function() return { GetXY = function() return 0.56412, 0.47123 end } end,
  GetMapInfo = function() return { name = "Marche de l'Ouest" } end,
  SetUserWaypoint = function(point) WAYPOINT = point end,
}
UiMapPoint = { CreateFromCoordinates = function(m, x, y) return { m = m, x = x, y = y } end }
DONE = { [65] = true }
C_QuestLog = { IsQuestFlaggedCompleted = function(id) return DONE[id] == true end }
function shownRows()
  local out = {}
  for _, f in ipairs(frames) do
    local text = rawget(f, "text")
    if text and f.shown and rawget(text, "label") then out[#out + 1] = { text.label, f } end
  end
  return out
end
"""


def rows_of(lua):
    return [(r[1], r[2]) for r in lua.globals().shownRows().values()]


def click(frame):
    frame.Click(frame)  # méthode Lua : le cadre en premier argument


def printed(lua):
    return list(lua.globals().printed.values())


def test_hunt_recording_in_game():
    """L'addon note donneur, position, niveaux, faction, et la suite quand le même PNJ enchaîne après un rendu."""
    lua = run_addon(None, QUEST_API)
    g = lua.globals()
    g.fire("ADDON_LOADED", "WowPlanner")
    g.fire("PLAYER_LOGIN")
    lua.execute("""
      NPC = { guid = "Creature-0-1-2-3-234-0000AAAA", name = "Gryan Stoutmantle" }
      GOSSIP = { { questID = 65, title = "La Confrérie défias", questLevel = 14 },
                 { questID = 999, title = "Autre", questLevel = 15 } }
    """)
    g.fire("GOSSIP_SHOW")
    lua.execute("DETAIL = 65")
    g.fire("QUEST_DETAIL")
    g.fire("QUEST_COMPLETE")
    g.fire("QUEST_TURNED_IN", 65)
    lua.execute("""clock = clock + 3
      GOSSIP = { { questID = 132, title = "La Confrérie défias (2)", questLevel = 15 },
                 { questID = 999, title = "Autre", questLevel = 15 } }""")
    g.fire("GOSSIP_SHOW")  # 132 apparaît juste après le rendu : suite ; 999 était déjà proposée : pas une suite
    lua.execute('NPC = { guid = "Player-1-0001" }; DETAIL = 1234')
    g.fire("QUEST_DETAIL")  # quête commencée par un objet du sac : pas de position
    lua.execute("""NPC = { guid = "Creature-0-1-2-3-500-0000BBBB", name = "Loin" }; clock = clock + 500
      GOSSIP = { { questID = 777, title = "Trop tard", questLevel = 15 } }""")
    g.fire("GOSSIP_SHOW")  # autre PNJ, longtemps après : pas de suite

    hunt = lua_to_python(g.WowPlannerDB.hunt)
    q = hunt["quests"][65]
    assert (q["npc"], q["npcId"], q["kind"], q["map"], q["zone"]) == ("Gryan Stoutmantle", 234, "npc", 1436, "Marche de l'Ouest")
    assert (q["x"], q["y"], q["level"], q["plevel"], q["faction"], q["by"]) == (0.5641, 0.4712, 14, 20, "alliance", "Elwyn")
    assert hunt["quests"][1234]["kind"] == "item" and "map" not in hunt["quests"][1234]
    assert set(hunt["links"]) == {"65>132"}

    # Ce que le client envoie au site, puis ce que le site en lit.
    saved = "WowPlannerDB = " + to_lua(lua_to_python(g.WowPlannerDB)) + "\n"
    payload = client.inventory_payload(client.parse_lua_assignments(saved))
    sightings, links = parse_hunt(json.loads(json.dumps(payload["hunt"])))
    assert links == [(65, 132)] and {s.quest_id for s in sightings} == {65, 132, 999, 1234, 777}
    gryan = next(s for s in sightings if s.quest_id == 65)
    assert (gryan.npc_id, gryan.map_id, gryan.x, gryan.player_level, gryan.faction) == (234, 1436, 0.5641, 20, "alliance")


def test_hunt_merge_data_file_and_window(tmp_path):
    """Le site fusionne les relevés de la guilde (premier donneur gardé, plus bas niveau, factions) et prépare
    Data.lua ; la fenêtre de l'addon montre la suite de quêtes, les donneurs repérés ou non, et pose le waypoint."""
    from wowplanner.db import Database
    from wowplanner.quests import Sighting, lua_data

    db = Database(tmp_path / "t.db")
    now = 1_800_000_000
    db.upsert_quests([
        {"id": 166, "title": "La Confrérie défias", "area_id": 1581, "kind": "Donjon", "faction": None,
         "description": "x", "xp": 3000, "money": 100, "items": None},
        {"id": 214, "title": "Les masques rouges en soie", "area_id": 1581, "kind": "Donjon", "faction": "horde",
         "description": None, "xp": None, "money": None, "items": None},
    ], now)
    first = Sighting(65, "La Confrérie défias", 234, "Gryan Stoutmantle", "npc", 1436, "Marche de l'Ouest", 0.56, 0.47,
                     14, 20, "alliance", "Elwyn", now)
    discovered, new_links = db.store_hunt([first], [(65, 132), (132, 166)], now)
    assert discovered == [65] and new_links == 2
    other = Sighting(65, None, 999, "Imposteur", "npc", 1, "Ailleurs", 0.1, 0.1, None, 12, "horde", "Grom", now + 5)
    discovered, new_links = db.store_hunt([other], [(65, 132)], now + 5)
    assert discovered == [] and new_links == 0
    row = db.quest_rows()[65]
    assert (row["npc_name"], row["map_id"], row["min_level"], row["factions"]) == ("Gryan Stoutmantle", 1436, 12, ["alliance", "horde"])
    assert row["found_by"] == "Elwyn"
    version = db.quests_version()
    db.store_hunt([Sighting(132, "Suite", player_level=15, character="Elwyn", seen_at=now)], [], now + 9)
    assert db.quests_version() != version
    assert db.quests_to_fetch({166, 214, 300}) == [65, 132, 300]  # suites relevées et nouvelles quêtes de donjon

    text = lua_data({"ts": now, "generated": now, "items": [[2589, 1200, 1500, 30]]}, db.quest_rows(), db.quest_links())
    assert "found = 0, total = 2" in text  # les 2 quêtes des Mortemines : donneurs pas encore repérés
    lua = run_addon(None, QUEST_API, data=text)
    g = lua.globals()
    assert g.WowPlannerData["items"][2589][1] == 1200  # les prix restent au même endroit
    g.fire("ADDON_LOADED", "WowPlanner")
    g.fire("PLAYER_LOGIN")
    g.SlashCmdList.WOWPLANNER("quetes")
    shown = [t for t, _ in rows_of(lua)]
    # Niveau 20, Alliance : les donjons de la tranche, même sans quête connue ; pas ceux en territoire Horde.
    heads = [t for t in shown if "|cffffd100-|r" in t]
    assert any("La Salle des Thanes" in t and "côté Alliance" in t for t in heads)
    assert not any("Ruines de Lordaeron" in t for t in shown)
    wc = next(i for i, t in enumerate(shown) if "Cavernes des lamentations" in t)
    assert "pas encore chargées" in shown[wc + 1]
    dm = next(i for i, t in enumerate(shown) if "Les Mortemines" in t)
    assert "17-26" in shown[dm] and "2 quêtes" in shown[dm]
    steps = shown[dm + 1:dm + 7]
    assert "1/3" in steps[0] and "La Confrérie défias" in steps[0] and "ReadyCheck-Ready" in steps[0]  # déjà faite
    assert "Gryan Stoutmantle" in steps[1] and "Marche de l'Ouest 56, 47" in steps[1]
    assert "2/3" in steps[2] and "dès niv. 15" in steps[2] and "pas encore repéré" in steps[3]
    assert "3/3" in steps[4] and "(finale)" in steps[4] and "pas encore repéré" in steps[5]
    assert "Donjon d'Ombrecroc" in shown[dm + 7]
    assert not any("masques rouges" in t for t in shown)  # quête Horde, joueur Alliance

    click(rows_of(lua)[dm + 2][1])  # clic sur le donneur : épingle sur la carte du jeu
    assert (g.WAYPOINT.m, g.WAYPOINT.x) == (1436, 0.56)
    lua.execute("TomTom = { AddWaypoint = function(self, m, x, y, opts) TT = { m, x, y, opts.title } end }")
    click(rows_of(lua)[dm + 1][1])  # avec TomTom : sa flèche
    assert g.TT[1] == 1436 and "Gryan Stoutmantle" in g.TT[4]
    click(rows_of(lua)[dm + 4][1])  # donneur inconnu : un message, pas de waypoint
    assert "toi de le trouver" in printed(lua)[-1]
    click(rows_of(lua)[dm][1])  # replier les Mortemines
    assert "Donjon d'Ombrecroc" in rows_of(lua)[dm + 1][0]

    lua.execute("LEVEL = 70")  # aucun donjon à ce niveau : tout s'affiche à la demande
    g.SlashCmdList.WOWPLANNER("quetes")
    g.SlashCmdList.WOWPLANNER("quetes")
    assert "Aucun donjon de ton niveau" in rows_of(lua)[0][0]
    lua.execute("WowPlannerDB.settings.showAll = true")
    g.SlashCmdList.WOWPLANNER("quetes")
    g.SlashCmdList.WOWPLANNER("quetes")
    shown = [t for t, _ in rows_of(lua)]
    assert "Gouffre de Ragefeu" in shown[0] and any("Ruines de Lordaeron" in t and "côté Horde" in t for t in shown)
    g.SlashCmdList.WOWPLANNER("")
    assert any("quêtes de donjon : 2 connues, donneur repéré pour 0" in t for t in printed(lua))
    db.close()


def test_quests_window_without_data():
    lua = run_addon({"ts": 1, "generated": 1, "items": []}, QUEST_API)
    g = lua.globals()
    g.fire("ADDON_LOADED", "WowPlanner")
    g.fire("PLAYER_LOGIN")
    g.SlashCmdList.WOWPLANNER("quetes")
    assert "client WoW Planner 1.3 ou plus" in rows_of(lua)[0][0]
    g.SlashCmdList.WOWPLANNER("")
    assert any("pas de quêtes de donjon dans les données" in t for t in printed(lua))
    g.SlashCmdList.WOWPLANNER("bouton")
    assert "masqué" in printed(lua)[-1] and g.WowPlannerDB.settings.hideButton


def test_quest_groups_and_parsing():
    from wowplanner import dungeons
    from wowplanner.quests import GROUPS, GROUPS_SPEC, ordered_chain, parse_blizzard_quest

    known = {d.slug for d in dungeons.DUNGEONS} | {r.slug for r in dungeons.RAIDS}
    for _, slugs, _ in GROUPS_SPEC:
        assert set(slugs) <= known, slugs  # pas de faute dans les noms des donjons
    assert len(GROUPS) == len(GROUPS_SPEC)
    sm = next(g for g in GROUPS if g.name == "Monastère écarlate")
    assert (sm.low, sm.high, len(sm.slugs)) == (30, 46, 4)
    assert not any(g.raid for g in GROUPS[:-3]) and all(g.raid for g in GROUPS[-3:])

    row = parse_blizzard_quest({
        "id": 92753, "title": "Destruction dans les Mortemines", "area": {"id": 1581, "name": "Les Mortemines"},
        "type": {"name": "Donjon"}, "requirements": {"faction": {"type": "ALLIANCE"}},
        "rewards": {"experience": 3700, "money": {"value": 1800},
                    "items": {"choice_of": [{"item": {"id": 918, "name": "Sac"}}, {"item": {"id": 919, "name": "Autre"}}]}},
    })
    assert row["area_id"] == 1581 and row["faction"] == "alliance" and row["xp"] == 3700 and row["money"] == 1800
    assert json.loads(row["items"]) == [[918, "Sac"], [919, "Autre"]]
    assert parse_blizzard_quest({"title": "sans id"}) is None

    sightings, links = parse_hunt({
        "quests": [{"id": 5, "x": 2, "y": 0.5, "map": 1}, {"id": "x"},
                   {"id": 6, "x": 0.2, "y": 0.3, "map": 1436, "kind": "hack", "faction": "Horde"}],
        "links": [[1, 2], [3, 3], ["a", 1], [4]],
    })
    assert [s.quest_id for s in sightings] == [5, 6] and sightings[0].x is None and sightings[0].map_id is None
    assert sightings[1].source == "npc" and sightings[1].faction == "horde" and links == [(1, 2)]
    assert parse_hunt("garbage") == ([], [])
    assert ordered_chain(3, [(1, 2), (2, 3), (3, 4), (9, 3)]) == [1, 9, 2, 3, 4]


def test_quest_sync_step(tmp_path):
    """Synchro : quêtes des zones de donjon, puis seulement les nouvelles (et celles des suites relevées en jeu)."""
    from types import SimpleNamespace

    from wowplanner.armory import ArmoryError
    from wowplanner.cogs.sync import SyncCog
    from wowplanner.db import Database
    from wowplanner.quests import AREAS

    db = Database(tmp_path / "t.db")
    asked = []

    class FakeClient:
        async def get(self, path, namespace):
            assert namespace == "static-forever"
            asked.append(path)
            if path == "/data/wow/quest/area/1581":
                return {"quests": [{"id": 166, "name": "La Confrérie défias"}, {"id": 167, "name": "Oh, mon frère…"}]}
            if path.startswith("/data/wow/quest/area/"):
                return {"quests": []}
            qid = int(path.rsplit("/", 1)[1])
            if qid == 167:
                raise ArmoryError(404, path)
            return {"id": qid, "title": f"Quête {qid}", "area": {"id": 1581 if qid > 160 else 40}}

    armory = SimpleNamespace(available=True, client=FakeClient())
    bot = SimpleNamespace(config=SimpleNamespace(timezone=None, data_dir=tmp_path), db=db,
                          get_cog=lambda name: armory if name == "ArmoryCog" else None)
    cog = SyncCog.__new__(SyncCog)
    cog.bot = bot
    icon, text = asyncio.run(cog._quests(False))
    assert icon == "⚠️" and "2 quête(s) dans les donjons, 1/2 lue(s)" in text
    assert db.quest_rows()[166]["area_id"] == 1581 and len(asked) == len(AREAS) + 2
    db.store_hunt([], [(65, 166)], int(time.time()))  # suite relevée en jeu : sa première étape est demandée
    asked.clear()
    asyncio.run(cog._quests(False))
    assert [p for p in asked if not p.startswith("/data/wow/quest/area/")] == ["/data/wow/quest/65", "/data/wow/quest/167"]
    assert db.quest_rows()[65]["title"] == "Quête 65"
    db.close()


def test_quest_api(tmp_path):
    """/api/addon/data (Data.lua complet, ETag) et relevés de la chasse joints à l'inventaire."""
    aiohttp = pytest.importorskip("aiohttp")
    from wowplanner.addon import hash_token
    from wowplanner.db import Database
    from wowplanner.web import WebSite

    db = Database(tmp_path / "t.db")
    site = WebSite(db, lambda: 1)
    uid, token, now = 77, "wp_test", int(time.time())
    db.conn.execute(
        "INSERT INTO characters (user_id, name, wow_class, race, created_at) VALUES (?, 'Elwyn', 'mage', 'humain', 0)", (uid,)
    )
    db.conn.commit()
    db.set_addon_token(uid, hash_token(token), now)
    db.upsert_quests([{"id": 166, "title": "La Confrérie défias", "area_id": 1581, "kind": None, "faction": None,
                       "description": None, "xp": None, "money": None, "items": None}], now)
    got = {}

    async def scenario():
        await site.start("127.0.0.1", 0)
        port = next(iter(site._runner.sites))._server.sockets[0].getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        auth = {"Authorization": f"Bearer {token}"}
        async with aiohttp.ClientSession() as s:
            async with s.get(base + "/api/addon/data") as r:
                got["anon"] = r.status
            async with s.get(base + "/api/addon/data", headers=auth) as r:
                got["data"] = (r.status, await r.text(), r.headers.get("ETag"))
            async with s.get(base + "/api/addon/data", headers={**auth, "If-None-Match": got["data"][2]}) as r:
                got["cached"] = r.status
            body = {"characters": [{"name": "Elwyn", "bags": {}}], "hunt": {
                "quests": [{"id": 166, "npc": "Gryan", "map": 1436, "x": 0.5, "y": 0.4, "plevel": 18, "by": "Elwyn"}],
                "links": [[65, 166]]}}
            async with s.post(base + "/api/addon/inventaire", headers=auth, json=body) as r:
                got["inv"] = await r.json()
            async with s.post(base + "/api/addon/inventaire", headers=auth, json=body) as r:
                got["inv2"] = await r.json()
            async with s.get(base + "/api/addon/data", headers={**auth, "If-None-Match": got["data"][2]}) as r:
                got["after"] = (r.status, await r.text())
        await site.stop()

    asyncio.run(scenario())
    status, text, etag = got["data"]
    assert got["anon"] == 401 and status == 200 and "WowPlannerData = {" in text and "La Confrérie défias" in text
    assert got["cached"] == 304
    assert got["inv"]["hunt"] == {"discovered": 1, "dungeon": ["La Confrérie défias"], "links": 1}
    assert got["inv2"]["hunt"] == {"discovered": 0, "dungeon": [], "links": 0}  # déjà connu : rien de neuf
    status, text = got["after"]
    assert status == 200 and 'npc="Gryan"' in text and "found = 1, total = 1" in text and "[65]={next={166}}" in text
    db.close()
