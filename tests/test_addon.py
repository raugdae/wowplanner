"""Addon WoW (Lua, exécuté avec lupa en simulant l'API du jeu), client local (lecture des SavedVariables, Data.lua) et
API du site (/api/addon/…)."""
import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

from wowplanner.addon import hash_token, match_recipes, parse_inventory, profession_key, GameRecipe

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "client"))
import wowplanner_client as client  # noqa: E402

ADDON = ROOT / "addon" / "WowPlanner"

# Simulation minimale de l'API du jeu : 2 sacs, la banque, un métier ouvert, l'enchantement, l'infobulle.
WOW_API = r"""
NUM_BAG_SLOTS, NUM_BANKBAGSLOTS, BANK_CONTAINER = 4, 6, -1
printed = {}
DEFAULT_CHAT_FRAME = { AddMessage = function(self, text) printed[#printed + 1] = text end }
floor = math.floor
strlower, strtrim = string.lower, function(s) return (s:gsub("^%s+", ""):gsub("%s+$", "")) end
function select(n, ...) local t = { ... } return t[n] end
function date(fmt, t) return os.date(fmt, t) end
function time() return 1795000000 end
function GetCoinTextureString(c) return c .. "c" end
BAGS = {
  [0] = { [1] = { 2589, 20 }, [2] = { 2589, 7 }, [3] = { 4306, 5 } },
  [1] = { [1] = { 2592, 3 } },
  [-1] = { [1] = { 4306, 40 } },
  [5] = { [2] = { 14047, 12 } },
}
C_Container = {
  GetContainerNumSlots = function(bag) return BAGS[bag] and 4 or 0 end,
  GetContainerItemInfo = function(bag, slot)
    local x = BAGS[bag] and BAGS[bag][slot]
    if x then return { itemID = x[1], stackCount = x[2], hyperlink = "|Hitem:" .. x[1] .. ":0|h" } end
  end,
}
function GetMoney() return 123456 end
function UnitLevel() return 42 end
function UnitName() return "Elwyn" end
function UnitClass() return "Mage", "MAGE" end
function GetRealmName() return "Forever" end
SKILLS = { { "Métiers", true }, { "Couture", false, false, 215 }, { "Secourisme", false, false, 150 },
  { "Armes", true }, { "Épées", false, false, 200 } }
function GetNumSkillLines() return #SKILLS end
function GetSkillLineInfo(i) local s = SKILLS[i] return s[1], s[2], s[3], s[4] end
TRADE = { { "Tissus", "header" }, { "Rouleau d'étoffe de lin", "easy", 2996 }, { "Chemise rouge", "optimal", 2575 } }
function GetTradeSkillLine() return "Couture", 215, 225 end
function GetNumTradeSkills() return #TRADE end
function GetTradeSkillInfo(i) return TRADE[i][1], TRADE[i][2] end
function GetTradeSkillItemLink(i) return TRADE[i][3] and ("|Hitem:" .. TRADE[i][3] .. ":0|h") end
function GetCraftDisplaySkillLine() return "Enchantement", 120, 150 end
function GetNumCrafts() return 1 end
function GetCraftInfo(i) return "Enchanter bracelets - Endurance", "", "medium" end
function GetCraftItemLink(i) return "|Henchant:7457|h" end
reloaded = false
function ReloadUI() reloaded = true end
SlashCmdList = {}

local function newTooltip(name)
  local t = { lines = {}, scripts = {}, name = name }
  function t:HookScript(event, fn) self.scripts[event] = fn end
  function t:AddDoubleLine(a, b) self.lines[#self.lines + 1] = a .. " = " .. b end
  function t:AddLine(a) self.lines[#self.lines + 1] = a end
  function t:GetItem() return "x", self.link end
  function t:GetOwner() return self.owner end
  return t
end
GameTooltip, ItemRefTooltip = newTooltip("GameTooltip"), newTooltip("ItemRefTooltip")

frames = {}
function CreateFrame()
  local f = { events = {} }
  function f:RegisterEvent(e) self.events[e] = true end
  function f:SetScript(_, fn) self.handler = fn end
  frames[#frames + 1] = f
  return f
end
function fire(event, ...) for _, f in ipairs(frames) do if f.events[event] then f.handler(f, event, ...) end end end

function hover(link, owner)
  GameTooltip.lines, GameTooltip.link, GameTooltip.owner = {}, link, owner
  GameTooltip.scripts.OnTooltipSetItem(GameTooltip)
  return GameTooltip.lines
end
function button(name, bag, slot)
  return { GetName = function() return name end, GetID = function() return slot end,
    GetParent = function() return { GetID = function() return bag end } end }
end
"""


def to_lua(value, indent=0) -> str:
    """Sérialise comme le jeu le fait pour les SavedVariables."""
    if isinstance(value, dict):
        pad = "\t" * (indent + 1)
        parts = []
        for k, v in value.items():
            key = f"[{k}]" if isinstance(k, (int, float)) else f'["{k}"]'
            parts.append(f"{pad}{key} = {to_lua(v, indent + 1)},")
        return "{\n" + "\n".join(parts) + "\n" + "\t" * indent + "}"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'
    return repr(value)


def lua_to_python(obj):
    if hasattr(obj, "items"):
        return {k: lua_to_python(v) for k, v in obj.items()}
    return obj


def run_addon(prices: dict | None, extra: str = ""):
    lupa = pytest.importorskip("lupa")
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(WOW_API + extra)
    data = client.lua_prices(prices) if prices else (ADDON / "Data.lua").read_text(encoding="utf-8")
    lua.execute(data)
    lua.execute((ADDON / "WowPlanner.lua").read_text(encoding="utf-8"))
    return lua


def test_addon_lua_scans_and_tooltips():
    prices = {"ts": 1795000000 - 3600, "generated": 1795000000, "items": [[2589, 1200, 1500, 340], [4306, 900, 900, 0]]}
    lua = run_addon(prices)
    fire = lua.globals().fire
    fire("ADDON_LOADED", "WowPlanner")
    fire("PLAYER_LOGIN")
    fire("BANKFRAME_OPENED")
    fire("TRADE_SKILL_SHOW")
    fire("CRAFT_SHOW")
    g = lua.globals()

    # Infobulles : prix unitaire, médian, pile survolée dans un sac, ventes ; rien pour un objet absent des prix.
    lines = list(g.hover("|Hitem:2589:0|h", g.button("ContainerFrame1Item2", 0, 1)).values())
    assert lines[0].endswith("= 1200c") and "médian" in lines[1] and lines[2].endswith("= 24000c")
    assert lines[3].endswith("~340 / jour")
    lines = list(g.hover("|Hitem:4306:0|h", g.button("BankFrameItem1", -1, 1)).values())
    assert len(lines) == 2 and lines[1].endswith("= 36000c")  # médian = plus bas : pas répété ; pile de 40
    assert len(g.hover("|Hitem:9999:0|h", None)) == 0
    g.SlashCmdList.WOWPLANNER("off")
    assert len(g.hover("|Hitem:2589:0|h", None)) == 0
    g.SlashCmdList.WOWPLANNER("on")
    g.SlashCmdList.WOWPLANNER("maj")
    assert g.reloaded

    # Ce que le jeu enregistre, relu par le client puis par le site.
    saved = "WowPlannerDB = " + to_lua(lua_to_python(g.WowPlannerDB)) + "\n"
    payload = client.inventory_payload(client.parse_lua_assignments(saved))
    (c,) = payload["characters"]
    assert c["name"] == "Elwyn" and c["level"] == 42 and c["money"] == 123456
    assert c["bags"] == {"2589": 27, "4306": 5, "2592": 3} and c["bank"] == {"4306": 40, "14047": 12}
    assert c["professions"] == {"Couture": 215, "Secourisme": 150, "Épées": 200}
    (game,) = parse_inventory(json.loads(json.dumps(payload)))
    assert game.professions == {"couture": 215, "secourisme": 150}  # les armes ne sont pas des métiers
    assert {r.item for r in game.recipes["couture"]} == {2996, 2575}
    assert game.recipes["enchantement"][0].spell == 7457


def test_addon_reagent_bag():
    """Client avec un emplacement « composants » (conteneur 5) : lu avec les sacs, banque décalée d'un cran."""
    lua = run_addon(None, """
NUM_REAGENTBAG_SLOTS = 1
BAGS[5] = { [1] = { 2447, 60 } }   -- sac de composants (herbes)
BAGS[6] = { [3] = { 14047, 12 } }  -- premier sac de banque
""")
    g = lua.globals()
    g.fire("ADDON_LOADED", "WowPlanner")
    g.fire("PLAYER_LOGIN")
    g.fire("BANKFRAME_OPENED")
    me = g.WowPlannerDB.chars["Elwyn - Forever"]
    assert me.bags[2447] == 60 and me.bags[14047] is None
    assert me.bank[14047] == 12 and me.bank[4306] == 40 and me.bank[2447] is None
    g.SlashCmdList.WOWPLANNER("sacs")
    shown = " | ".join(g.printed.values())
    assert "conteneurs 0 à 5" in shown and "conteneur 5 : 4 emplacements, 1 occupés" in shown
    assert "conteneur 6 : 4 emplacements, 1 occupés (pas lu" in shown


def test_addon_without_prices():
    lua = run_addon(None)
    g = lua.globals()
    g.fire("ADDON_LOADED", "WowPlanner")
    g.fire("PLAYER_LOGIN")
    assert len(g.hover("|Hitem:2589:0|h", None)) == 0
    g.SlashCmdList.WOWPLANNER("")
    assert "pas encore de prix" in "".join(g.printed.values())


def test_lua_parser_and_prices_file(tmp_path):
    text = r'''
WowPlannerDB = {
	["chars"] = {
		["Elwyn - Forever"] = {
			["name"] = "Elwyn",
			["note"] = "a \"b\"\n\233t\195\169", -- commentaire
			["list"] = {
				1, -- [1]
				2.5, -- [2]
				-3, -- [3]
			},
			["flag"] = true,
			[12] = false,
			["none"] = nil,
		},
	},
}
Other = { x = 1, [2] = "y" }
'''
    got = client.parse_lua_assignments(text)
    elwyn = got["WowPlannerDB"]["chars"]["Elwyn - Forever"]
    assert elwyn["note"] == 'a "b"\n\ufffdté' and elwyn["list"] == [1, 2.5, -3] and elwyn["flag"] is True
    assert elwyn[12] is False and got["Other"] == {"x": 1, 2: "y"}
    with pytest.raises(client.LuaError):
        client.parse_lua_assignments("X = { 1, 2")
    # Data.lua relu par le parseur (même syntaxe).
    data = client.parse_lua_assignments(client.lua_prices({"ts": 5, "generated": 6, "items": [[10, 1, 2, 3]]}))
    assert data["WowPlannerData"] == {"ts": 5, "generated": 6, "items": {10: [1, 2, 3]}}


def test_client_game_folder_and_install(tmp_path):
    game = tmp_path / "World of Warcraft"
    era = game / "_classic_era_"
    (era / "WTF" / "Account" / "ABC" / "SavedVariables").mkdir(parents=True)
    assert client.game_root(game) == era and client.game_root(era / "WTF") == era
    assert client.game_root(tmp_path / "nope") is None
    assert client.install_addon(era, ADDON) is True
    installed = era / "Interface" / "AddOns" / "WowPlanner"
    assert (installed / "WowPlanner.toc").read_text(encoding="utf-8").startswith("## Interface: 16001")
    (installed / "Data.lua").write_text("WowPlannerData = { ts = 1 }", encoding="utf-8")
    assert client.install_addon(era, ADDON) is False  # rien de changé, prix gardés
    assert "ts = 1" in (installed / "Data.lua").read_text(encoding="utf-8")
    sv = era / "WTF" / "Account" / "ABC" / "SavedVariables" / "WowPlanner.lua"
    sv.write_text("WowPlannerDB = {}", encoding="utf-8")
    assert client.saved_variables(era) == [sv]


def test_addon_payload_parsing():
    assert profession_key("Dépeçage") == "depecage" and profession_key("First Aid") == "secourisme"
    assert profession_key("Épées") is None
    chars = parse_inventory({"characters": [
        {"name": " Elwyn ", "level": 300, "bags": {"12": 3, "x": 1, "13": -4, "14": True}, "bank": None,
         "professions": {"Minage": 75, "Pêche": "?"}},
        "garbage", {"name": ""},
    ]})
    assert len(chars) == 1 and chars[0].name == "Elwyn" and chars[0].level is None
    assert chars[0].bags == {12: 3} and chars[0].bank is None and chars[0].professions == {"minage": 75, "peche": None}
    with pytest.raises(ValueError):
        parse_inventory({"nope": 1})
    known = [{"id": 1, "name": "Rouleau d'étoffe de lin", "name_en": "Bolt of Linen Cloth", "crafted_item_id": 2996},
             {"id": 2, "name": "Enchanter bracelets : endurance", "name_en": "Enchant Bracer - Stamina",
              "crafted_item_id": None}]
    ids, missing = match_recipes([GameRecipe(2996, None, "x"), GameRecipe(None, 7457, "Enchant Bracer - Stamina"),
                                  GameRecipe(None, None, "Inconnue")], known)
    assert ids == {1, 2} and missing == 1


def test_find_character_by_game_name():
    from types import SimpleNamespace
    from wowplanner.webaddon import find_character

    hollie, holly2, grom = (SimpleNamespace(name=n) for n in ("Hollie Tétine", "Hollie", "Grom Hurlenfer"))
    assert find_character("Hollie", [hollie, grom]) is hollie  # le jeu ne donne que le premier mot
    assert find_character("hollie tetine", [hollie]) is hollie
    assert find_character("Hollie", [hollie, holly2]) is holly2  # le nom exact passe avant
    twins = [hollie, SimpleNamespace(name="Hollie Autre")]
    assert find_character("Hollie", twins) is None and find_character("Bob", [grom]) is None


def test_addon_api(tmp_path):
    aiohttp = pytest.importorskip("aiohttp")
    from wowplanner.db import Database
    from wowplanner.web import WebSite

    db = Database(tmp_path / "t.db")
    site = WebSite(db, lambda: 1)
    uid = 77
    db.conn.execute(
        "INSERT INTO characters (user_id, name, wow_class, race, created_at) VALUES (?, 'Elwyn', 'mage', 'humain', 0)",
        (uid,),
    )
    cid = db.get_characters(uid)[0].id
    db.conn.execute("INSERT INTO recipes (id, profession, name_en, crafted_item_id) VALUES (9, 'couture', 'Bolt', 2996)")
    db.replace_character_recipes(cid, {"couture": []})
    now = int(time.time())
    db.conn.execute("INSERT INTO ah_latest VALUES (2589, ?, 1200, 1500, 50, 4)", (now,))
    db.store_ah_sales(now // 3600 * 3600, {2589: 30})
    db.conn.commit()
    token = "wp_test"
    db.set_addon_token(uid, hash_token(token), now)
    got = {}

    async def scenario():
        await site.start("127.0.0.1", 0)
        port = next(iter(site._runner.sites))._server.sockets[0].getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        auth = {"Authorization": f"Bearer {token}"}
        async with aiohttp.ClientSession() as s:
            async with s.get(base + "/api/addon/prix") as r:
                got["anon"] = r.status
            async with s.get(base + "/api/addon/moi", headers=auth) as r:
                got["me"] = await r.json()
            async with s.get(base + "/api/addon/prix", headers=auth) as r:
                got["prices"] = (r.status, await r.json(), r.headers.get("ETag"))
            async with s.get(base + "/api/addon/prix", headers={**auth, "If-None-Match": got["prices"][2]}) as r:
                got["cached"] = r.status
            body = {"characters": [
                {"name": "elwyn", "level": 33, "money": 99, "updated_at": now, "bags": {"2589": 4}, "bank": {"2589": 6},
                 "bank_at": now, "professions": {"Couture": 120},
                 "recipes": {"Couture": [{"item": 2996, "name": "Rouleau"}, {"item": 1, "name": "?"}]}},
                {"name": "Inconnu", "bags": {}},
            ]}
            async with s.post(base + "/api/addon/inventaire", headers=auth, json=body) as r:
                got["inv"] = (r.status, await r.json())
            body["characters"][0].update(bags={"2589": 1}, bank=None)  # banque pas rouverte : gardée
            async with s.post(base + "/api/addon/inventaire", headers=auth, json=body) as r:
                got["inv2"] = r.status
            async with s.post(base + "/api/addon/inventaire", headers=auth, data="{oops") as r:
                got["bad"] = r.status
            async with s.get(base + "/addon/WowPlanner.zip") as r:
                got["zip"] = (r.status, (await r.read())[:2])
        await site.stop()

    asyncio.run(scenario())
    assert got["anon"] == 401 and got["me"] == {"characters": ["Elwyn"]}
    status, prices, etag = got["prices"]
    assert status == 200 and prices["items"] == [[2589, 1200, 1500, 30]] and got["cached"] == 304
    assert got["inv"] == (200, {"updated": ["Elwyn"], "unknown": ["Inconnu"], "unmatched_recipes": 1})
    assert got["inv2"] == 200 and got["bad"] == 400
    meta, items = db.game_inventory(cid)
    assert items == {2589: 7} and meta["bank_at"] == now and meta["money"] == 99
    character = db.get_character(cid)
    assert character.level == 33 and character.professions == {"couture": 120}
    assert db.character_recipe_ids(cid) == {9}
    db.replace_character_recipes(cid, {"couture": []})  # synchro armurerie : la recette vue en jeu reste
    assert db.character_recipe_ids(cid) == {9}
    assert got["zip"] == (200, b"PK")
    db.close()
