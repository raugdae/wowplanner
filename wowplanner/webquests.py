"""Quêtes de donjon sur le site : section « Quêtes » des fiches de donjon et compteur de la chasse au trésor.

Les quêtes viennent de l'API Blizzard ; donneurs, positions, niveaux et suites sont relevés en jeu par les membres
(addon WoW Planner, voir quests.py). La page est publique : qui a repéré quoi n'est montré qu'aux membres connectés.
"""
from __future__ import annotations

from typing import Any

from .db import Database
from .quests import AREAS, QuestGroup, group_of_slug, ordered_chain
from .webauction import money_html
from .webui import esc

FACTIONS = {"alliance": "Alliance", "horde": "Horde"}


def hunt_counts(db: Database) -> tuple[int, int]:
    """(quêtes de donjon dont le donneur est repéré, quêtes de donjon connues)."""
    rows = db.quest_rows()
    dungeon = [q for q in rows.values() if q.get("area_id") in AREAS]
    return sum(1 for q in dungeon if q.get("npc_name") or q.get("x") is not None), len(dungeon)


def hunt_banner(db: Database) -> str:
    found, total = hunt_counts(db)
    if not total:
        return ""
    pct = round(found * 100 / total)
    return (
        f'<div class="hunt"><b>🔎 Chasse au trésor</b> : {found}/{total} quêtes de donjon ont leur donneur repéré '
        f'<span class="hbar"><span style="width:{pct}%"></span></span>'
        '<small class="muted">Installe l\'addon WoW Planner : chaque quête qu\'un PNJ te propose en jeu complète la '
        "carte pour toute la guilde.</small></div>"
    )


def _way(q: dict[str, Any]) -> str:
    """Commande TomTom pour le donneur (zone en toutes lettres : comprise par TomTom dans un client français)."""
    if q.get("x") is None or not q.get("zone"):
        return ""
    return f"/way {q['zone']} {q['x'] * 100:.1f} {q['y'] * 100:.1f} {q.get('npc_name') or ''}".strip()


def _step(qid: int, q: dict[str, Any], index: int, count: int, in_dungeon: bool, show_names: bool) -> str:
    title = esc(q.get("title") or f"Quête {qid}")
    tags = []
    if q.get("quest_level"):
        tags.append(f'<span class="qtag">niv. {q["quest_level"]}</span>')
    if q.get("min_level"):
        tags.append(f'<span class="qtag">dès niv. {q["min_level"]}</span>')
    faction = q.get("faction")
    seen = q.get("factions") or []
    if faction in FACTIONS:
        tags.append(f'<span class="side {faction}">{FACTIONS[faction]}</span>')
    elif len(seen) == 1:
        tags.append(f'<span class="qtag" title="Vue en jeu seulement par des persos de cette faction pour l\'instant">'
                    f"vue côté {FACTIONS[seen[0]]}</span>")
    if in_dungeon and count > 1:  # seule, une quête de cette liste est forcément celle du donjon
        tags.append('<span class="qtag dq">dans le donjon</span>')
    if count > 1 and index == count:
        tags.append('<span class="qtag fin">finale</span>')

    if q.get("npc_name") or q.get("x") is not None:
        where = esc(q.get("zone") or "")
        if q.get("x") is not None:
            where += f' <span class="muted">{q["x"] * 100:.1f}, {q["y"] * 100:.1f}</span>'
        who = esc(q.get("npc_name") or ("Objet" if q.get("source") == "object" else "Donneur"))
        way = _way(q)
        copy = (f'<button type="button" class="copy" data-copy="{esc(way)}" title="Copier pour TomTom">'
                f"<code>{esc(way)}</code><span>Copier</span></button>") if way else ""
        credit = (f' <small class="muted">· repéré par {esc(q["found_by"])}</small>'
                  if show_names and q.get("found_by") else "")
        giver = f'<div class="giver">📍 <b>{who}</b> · {where}{credit}</div>{copy}'
    elif q.get("source") == "item":
        giver = '<div class="giver muted">Commence avec un objet.</div>'
    else:
        giver = '<div class="giver hunting">🔎 Donneur pas encore repéré : à toi de le trouver !</div>'

    rewards = []
    if q.get("xp"):
        rewards.append(f"{q['xp']:,} XP".replace(",", " "))
    if q.get("money"):
        rewards.append(money_html(q["money"]))
    items = [f'<a href="/hdv/objet/{int(i)}">{esc(name or f"objet {i}")}</a>' for i, name in q.get("items") or []]
    if items:
        rewards.append(" ou ".join(items) if len(items) > 1 else items[0])
    reward_html = f'<div class="qrew">🎁 {" · ".join(rewards)}</div>' if rewards else ""
    text = q.get("description")
    details = (f'<details class="qtext"><summary>Texte de la quête</summary><p>{esc(text)}</p></details>'
               if text else "")
    number = f'<span class="dot">{index}</span>' if count > 1 else '<span class="dot">!</span>'
    return (f'<li class="step{" in" if in_dungeon else ""}">{number}<div class="sbody"><b>{title}</b> {"".join(tags)}'
            f"{giver}{reward_html}{details}</div></li>")


def quests_section(db: Database, slug: str, show_names: bool) -> tuple[int, str] | None:
    """Onglet « Quêtes » de la fiche du donjon : (nombre de quêtes, contenu), None si ce donjon n'a pas de zone de
    quêtes connue."""
    group: QuestGroup | None = group_of_slug(slug)
    if group is None:
        return None
    rows = db.quest_rows()
    links = db.quest_links()
    ids = sorted(qid for qid, q in rows.items() if q.get("area_id") in group.areas)
    if not ids:
        return 0, '<p class="empty">Quêtes pas encore lues dans l\'API Blizzard (synchro de nuit).</p>'
    chains, listed = [], set()
    for qid in ids:
        if qid in listed:
            continue
        chain = ordered_chain(qid, links)
        listed.update(chain)
        chains.append(chain)
    blocks = []
    for chain in chains:
        steps = "".join(
            _step(qid, rows.get(qid, {}), i, len(chain), rows.get(qid, {}).get("area_id") in group.areas, show_names)
            for i, qid in enumerate(chain, 1)
        )
        head = (f'<p class="qchain-head">Suite de {len(chain)} quêtes</p>' if len(chain) > 1 else "")
        blocks.append(f'<div class="qchain">{head}<ol class="route quests">{steps}</ol></div>')
    found = sum(1 for qid in ids if rows[qid].get("npc_name") or rows[qid].get("x") is not None)
    shared = (f" Quêtes communes aux {len(group.slugs)} ailes : {esc(group.name)}." if len(group.slugs) > 1 else "")
    return len(ids), f"""<p class="sub">{len(ids)} quête(s) liée(s) à ce donjon, avec leurs suites ; donneur repéré pour {found}/{len(ids)}.{shared}
Le niveau « dès » est le plus bas niveau auquel un membre s'est vu proposer la quête.</p>
{"".join(blocks)}"""
