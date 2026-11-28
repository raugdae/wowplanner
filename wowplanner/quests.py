"""Quêtes de donjon : liste officielle (API Blizzard) complétée par la « chasse au trésor » de la guilde (addon).

- **Blizzard** (namespace static-forever) : les quêtes rangées par zone, dont les zones de donjon ; pour chaque quête,
  titre français, texte, récompenses, parfois la faction. Pas de niveau, ni de donneur, ni de suite de quêtes.
- **L'addon** relève en jeu ce qui manque, quand un PNJ propose une quête : son donneur et la position du joueur
  (le waypoint), le niveau de la quête, le plus bas niveau de joueur à qui elle a été proposée, et les suites (rendre
  une quête puis se voir proposer la suivante par le même PNJ). Le client l'envoie avec l'inventaire ; le site
  fusionne les relevés de toute la guilde.

Rien n'est repris d'une base tierce : la liste vient de Blizzard, le reste est observé par les membres.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable

from . import dungeons

# Zones de quêtes de l'API Blizzard -> donjons (slugs du site). Certaines zones couvrent plusieurs ailes (Monastère
# écarlate, Hache-Tripes, Stratholme, Pic de Rochenoire) : leurs quêtes sont communes à ces ailes.
GROUPS_SPEC: tuple[tuple[str, tuple[str, ...], tuple[int, ...]], ...] = (
    ("Gouffre de Ragefeu", ("ragefire-chasm",), (2437,)),
    ("La Salle des Thanes", ("hall-of-thanes",), (16919,)),
    ("Ruines de Lordaeron", ("ruins-of-lordaeron",), (16611,)),
    ("Cavernes des lamentations", ("wailing-caverns",), (718,)),
    ("Les Mortemines", ("the-deadmines",), (1581,)),
    ("Donjon d'Ombrecroc", ("shadowfang-keep",), (209, 236)),
    ("Profondeurs de Brassenoire", ("blackfathom-deeps",), (719,)),
    ("La Prison", ("the-stockade",), (717,)),
    ("Site de fouilles des Paluns", ("excavation-site-wetlands",), (16732,)),
    ("Cité de Dalaran", ("city-of-dalaran",), (279, 16544, 16560)),
    ("Gnomeregan", ("gnomeregan",), (133, 721)),
    ("Kraal de Tranchebauge", ("razorfen-kraul",), (1717,)),
    ("Monastère écarlate", ("scarlet-monastery-graveyard", "scarlet-monastery-library", "scarlet-monastery-armory",
                            "scarlet-monastery-cathedral"), (796,)),
    ("La Cité engloutie", ("the-drowned-city",), (16550,)),
    ("Souilles de Tranchebauge", ("razorfen-downs",), (722,)),
    ("Bastion de Krol'dok", ("kroldok-stronghold",), (16842,)),
    ("Uldaman", ("uldaman",), (1517,)),
    ("Zul'Farrak", ("zulfarrak",), (1176,)),
    ("Maraudon", ("maraudon",), (2100,)),
    ("Prison d'Alcaz", ("alcaz-prison",), (16620, 2079)),
    ("Le temple englouti", ("sunken-temple",), (1417, 1477)),
    ("Profondeurs de Rochenoire", ("blackrock-depths",), (1584,)),
    ("Hache-Tripes", ("dire-maul-east", "dire-maul-north", "dire-maul-west"), (2557,)),
    ("Repaire des Noiregueules", ("blackmaw-hold",), (16554,)),
    ("Pic de Rochenoire", ("lower-blackrock-spire", "upper-blackrock-spire"), (1583,)),
    ("Scholomance", ("scholomance",), (2057,)),
    ("Terrasse du Façonneur", ("shapers-terrace",), (16985,)),
    ("Stratholme", ("stratholme-main-gate", "stratholme-service-gate"), (2017,)),
    ("Sommet d'Hyjal", ("hyjal-summit",), (16597,)),
    ("Repaire d'Onyxia", ("onyxias-lair",), (2159,)),
    ("Cœur du Magma", ("molten-core",), (2717,)),
)

# Garde-fous sur ce que le client envoie.
MAX_SIGHTINGS = 5000
MAX_LINKS = 5000
MAX_QUEST_ID = 10_000_000


@dataclass(frozen=True)
class QuestGroup:
    key: str  # slug du premier donjon du groupe
    name: str
    slugs: tuple[str, ...]
    areas: tuple[int, ...]
    low: int
    high: int
    raid: bool


def _build_groups() -> tuple[QuestGroup, ...]:
    by_slug = {d.slug: d for d in dungeons.DUNGEONS}
    raids = {r.slug for r in dungeons.RAIDS}
    groups = []
    for name, slugs, areas in GROUPS_SPEC:
        found = [by_slug[s] for s in slugs if s in by_slug]
        raid = all(s in raids for s in slugs)
        if not found and not raid:
            continue  # donjon retiré de la liste du site
        low = min((d.low for d in found), default=dungeons.RAID_LEVEL)
        high = max((d.high for d in found), default=dungeons.RAID_LEVEL)
        groups.append(QuestGroup(slugs[0], name, slugs, areas, low, high, raid))
    return tuple(sorted(groups, key=lambda g: (g.raid, g.low, g.high, g.name)))


GROUPS: tuple[QuestGroup, ...] = _build_groups()
AREAS: dict[int, QuestGroup] = {area: g for g in GROUPS for area in g.areas}


def group_of_slug(slug: str) -> QuestGroup | None:
    return next((g for g in GROUPS if slug in g.slugs), None)


# ============================================================ API Blizzard


def parse_blizzard_quest(data: Any) -> dict[str, Any] | None:
    """Réponse de /data/wow/quest/{id} → ligne de la table quests (None si illisible)."""
    if not isinstance(data, dict) or not isinstance(data.get("id"), int):
        return None
    area = data.get("area") if isinstance(data.get("area"), dict) else {}
    kind = data.get("type") if isinstance(data.get("type"), dict) else {}
    faction = ((data.get("requirements") or {}).get("faction") or {}).get("type")
    rewards = data.get("rewards") if isinstance(data.get("rewards"), dict) else {}
    items: list[list[Any]] = []

    def collect(node: Any) -> None:  # objets en récompense, au choix ou non, où qu'ils soient rangés
        if isinstance(node, dict):
            item = node.get("item")
            if isinstance(item, dict) and isinstance(item.get("id"), int):
                items.append([item["id"], str(item.get("name") or "")])
                return
            for value in node.values():
                collect(value)
        elif isinstance(node, list):
            for value in node:
                collect(value)

    collect(rewards.get("items"))
    money = rewards.get("money")
    return {
        "id": data["id"], "title": str(data.get("title") or "")[:200] or None,
        "area_id": area.get("id") if isinstance(area.get("id"), int) else None,
        "kind": str(kind.get("name") or "")[:60] or None,
        "faction": {"ALLIANCE": "alliance", "HORDE": "horde"}.get(str(faction or "").upper()),
        "description": str(data.get("description") or "")[:4000] or None,
        "xp": rewards.get("experience") if isinstance(rewards.get("experience"), int) else None,
        "money": money.get("value") if isinstance(money, dict) and isinstance(money.get("value"), int) else None,
        "items": json.dumps(items, ensure_ascii=False) if items else None,
    }


# ============================================================ chasse au trésor (addon)


@dataclass
class Sighting:
    """Une quête proposée par un PNJ (ou un objet), vue en jeu par un membre."""
    quest_id: int
    title: str | None = None
    npc_id: int | None = None
    npc_name: str | None = None
    source: str = "npc"  # « npc », « object » (affiche, rocher…) ou « item » (objet du sac)
    map_id: int | None = None
    zone: str | None = None
    x: float | None = None  # 0-1 sur la carte map_id
    y: float | None = None
    quest_level: int | None = None
    player_level: int | None = None
    faction: str | None = None  # « alliance » / « horde » : faction du joueur qui l'a vue
    character: str | None = None
    seen_at: int = 0


def _int(value: Any, low: int, high: int) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = int(value)
    return value if low <= value <= high else None


def _coord(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
        return None
    return round(float(value), 4)


def _text(value: Any, size: int) -> str | None:
    return value.strip()[:size] or None if isinstance(value, str) else None


def parse_hunt(raw: Any) -> tuple[list[Sighting], list[tuple[int, int]]]:
    """Relevés envoyés par le client : {"quests": [{"id", "title", "npc", "npcId", "kind", "map", "zone", "x", "y",
    "level", "plevel", "faction", "by", "at"}], "links": [[précédente, suivante]]}. Ce qui est mal formé est ignoré."""
    if not isinstance(raw, dict):
        return [], []
    sightings: list[Sighting] = []
    entries = raw.get("quests") if isinstance(raw.get("quests"), list) else []
    for entry in entries[:MAX_SIGHTINGS]:
        if not isinstance(entry, dict):
            continue
        qid = _int(entry.get("id"), 1, MAX_QUEST_ID)
        if not qid:
            continue
        x, y = _coord(entry.get("x")), _coord(entry.get("y"))
        map_id = _int(entry.get("map"), 1, 100_000)
        if x is None or y is None or map_id is None:
            x = y = map_id = None
        kind = entry.get("kind") if entry.get("kind") in ("npc", "object", "item") else "npc"
        faction = str(entry.get("faction") or "").lower()
        sightings.append(Sighting(
            quest_id=qid, title=_text(entry.get("title"), 200), npc_id=_int(entry.get("npcId"), 1, MAX_QUEST_ID),
            npc_name=_text(entry.get("npc"), 80), source=kind, map_id=map_id, zone=_text(entry.get("zone"), 80),
            x=x, y=y, quest_level=_int(entry.get("level"), 1, 100), player_level=_int(entry.get("plevel"), 1, 100),
            faction=faction if faction in ("alliance", "horde") else None, character=_text(entry.get("by"), 40),
            seen_at=_int(entry.get("at"), 0, 2**40) or 0,
        ))
    links: list[tuple[int, int]] = []
    pairs = raw.get("links") if isinstance(raw.get("links"), list) else []
    for pair in pairs[:MAX_LINKS]:
        if isinstance(pair, list) and len(pair) == 2:
            prev, nxt = _int(pair[0], 1, MAX_QUEST_ID), _int(pair[1], 1, MAX_QUEST_ID)
            if prev and nxt and prev != nxt:
                links.append((prev, nxt))
    return sightings, links


# ============================================================ suites de quêtes


def chain_ids(start: Iterable[int], links: Iterable[tuple[int, int]]) -> set[int]:
    """Les quêtes de départ et tout ce qui les précède ou les suit (suites de quêtes complètes)."""
    before: dict[int, set[int]] = {}
    after: dict[int, set[int]] = {}
    for prev, nxt in links:
        after.setdefault(prev, set()).add(nxt)
        before.setdefault(nxt, set()).add(prev)
    seen = set(start)
    todo = list(seen)
    while todo:
        qid = todo.pop()
        for other in before.get(qid, set()) | after.get(qid, set()):
            if other not in seen:
                seen.add(other)
                todo.append(other)
    return seen


def ordered_chain(qid: int, links: Iterable[tuple[int, int]]) -> list[int]:
    """Suite de quêtes autour de qid, de la première à la dernière (ordre des étapes ; une quête n'apparaît
    qu'une fois, même si la suite a des branches)."""
    links = list(links)
    family = chain_ids([qid], links)
    before: dict[int, set[int]] = {}
    for prev, nxt in links:
        if prev in family and nxt in family:
            before.setdefault(nxt, set()).add(prev)
    order: list[int] = []
    placed: set[int] = set()
    remaining = set(family)
    while remaining:
        ready = sorted(q for q in remaining if not (before.get(q, set()) & remaining))
        if not ready:  # boucle (données incohérentes) : on place le reste tel quel
            ready = sorted(remaining)
        for q in ready:
            order.append(q)
            placed.add(q)
        remaining -= set(ready)
    return order


# ============================================================ Data.lua (prix + quêtes pour l'addon)


def lua_string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "") + '"'


def lua_data(prices: dict[str, Any], quests: dict[int, dict[str, Any]], links: list[tuple[int, int]]) -> str:
    """Data.lua complet de l'addon : prix de l'HdV (même format qu'avant) et quêtes de donjon.

    quests : id -> {"title", "area_id", "faction", "quest_level", "min_level", "npc_name", "zone", "map_id", "x", "y",
    "source"} (voir Database.quest_rows)."""
    lines = [
        "-- Écrit par le client WoW Planner (prix de l'hôtel des ventes, quêtes de donjon) : ne pas modifier.",
        f"WowPlannerData = {{ ts = {int(prices.get('ts') or 0)}, generated = {int(prices.get('generated') or 0)}, items = {{",
    ]
    for row in prices.get("items") or []:
        item, low, median, sold = (int(v) for v in row[:4])
        lines.append(f"[{item}]={{{low},{median},{sold}}},")
    lines.append("},")

    by_area: dict[int, list[int]] = {}
    for qid, q in quests.items():
        if q.get("area_id") in AREAS:
            by_area.setdefault(q["area_id"], []).append(qid)
    lines.append("dungeons = {")
    shown: set[int] = set()
    for g in GROUPS:
        ids = sorted({qid for area in g.areas for qid in by_area.get(area, [])})
        shown.update(ids)
        lines.append(
            f"{{n={lua_string(g.name)},lo={g.low},hi={g.high},raid={'true' if g.raid else 'false'},"
            f"q={{{','.join(map(str, ids))}}}}},"
        )
    lines.append("},")

    family = chain_ids(shown, links)
    before: dict[int, list[int]] = {}
    after: dict[int, list[int]] = {}
    for prev, nxt in links:
        if prev in family and nxt in family:
            after.setdefault(prev, []).append(nxt)
            before.setdefault(nxt, []).append(prev)
    lines.append("quests = {")
    found = 0
    for qid in sorted(family):
        q = quests.get(qid) or {}
        fields = []
        if q.get("title"):
            fields.append(f"t={lua_string(q['title'])}")
        for key, lua in (("quest_level", "lvl"), ("min_level", "min"), ("map_id", "map")):
            if q.get(key):
                fields.append(f"{lua}={int(q[key])}")
        if q.get("faction") in ("alliance", "horde"):
            fields.append(f"fac={lua_string(q['faction'][0].upper())}")
        for key, lua in (("npc_name", "npc"), ("zone", "zone"), ("source", "src")):
            if q.get(key):
                fields.append(f"{lua}={lua_string(str(q[key]))}")
        if q.get("x") is not None and q.get("y") is not None:
            fields.append(f"x={float(q['x']):.4f},y={float(q['y']):.4f}")
        if q.get("npc_name") or q.get("x") is not None:
            found += qid in shown
        if before.get(qid):
            fields.append(f"prev={{{','.join(map(str, sorted(before[qid])))}}}")
        if after.get(qid):
            fields.append(f"next={{{','.join(map(str, sorted(after[qid])))}}}")
        lines.append(f"[{qid}]={{{','.join(fields)}}},")
    lines.append("},")
    lines.append(f"found = {found}, total = {len(shown)} }}")
    return "\n".join(lines) + "\n"
