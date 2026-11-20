"""Blocs de la fiche d'un perso : équipement façon jeu, caractéristiques et priorités de stats, talents,
métiers, et équipement que la guilde sait fabriquer pour lui."""
from __future__ import annotations

import json
from datetime import datetime

from . import gear, proficiency, statsource
from .armory import icon_url
from .db import Character, Crafter, GuildRecipe
from .gamedata import (
    MAX_PROFESSION_SKILL,
    PROFESSIONS,
    class_label,
    is_primary,
    profession_label,
    roles_for,
)
from .recipes import normalize
from .roles import LABELS
from .webui import (
    QUALITY_COLORS,
    esc,
)

TALENT_COLUMNS = 4
TALENT_MAX_ROWS = 11  # au-delà : position farfelue renvoyée par l'API (doublons), hors grille


def _talent_ranks(group: dict) -> dict[int, tuple[int, str | None]]:
    return {t[0]: (t[2], t[3]) for spec in group.get("specs", []) for t in spec.get("talents", [])}


def talent_points(group: dict, trees: list[dict]) -> list[int]:
    """Points par arbre, dans l'ordre du jeu (ex. [0, 0, 14])."""
    ranks = _talent_ranks(group)
    by_spec = {s.get("spec_id"): s.get("points") or 0 for s in group.get("specs", [])}
    result = []
    for tree in trees:
        if tree["spec_id"] in by_spec:
            result.append(by_spec[tree["spec_id"]])
        else:
            result.append(sum(ranks.get(n["talent"], (0, None))[0] for n in tree["nodes"]))
    return result


def _talent_tooltip(node: dict, rank: int, current: str | None) -> str:
    meta = " · ".join(esc(node[k]) for k in ("cast", "cost", "range", "cooldown") if node.get(k))
    ranks = node.get("ranks") or []
    desc = current or (ranks[max(rank, 1) - 1] if ranks else "")
    nxt = ""
    if 0 < rank < node["max"] and len(ranks) > rank:
        nxt = f'<div class="next">Rang suivant :<span>{esc(ranks[rank])}</span></div>'
    return (
        f'<div class="tt"><b>{esc(node["name"])}</b><div class="lvl">Rang {rank}/{node["max"]}</div>'
        + (f'<div class="meta">{meta}</div>' if meta else "")
        + (f'<div class="desc">{esc(desc)}</div>' if desc else "")
        + nxt + "</div>"
    )


def talent_tree_html(tree: dict, ranks: dict[int, tuple[int, str | None]], points: int) -> str:
    nodes = [n for n in tree["nodes"] if 1 <= n["row"] <= TALENT_MAX_ROWS]
    base = min((n["col"] for n in nodes), default=0)
    in_grid = [n for n in nodes if 0 <= n["col"] - base < TALENT_COLUMNS]
    grid_talents = {n["talent"] for n in in_grid}
    cells = []
    for n in sorted(in_grid, key=lambda n: (n["row"], n["col"])):
        rank, current = ranks.get(n["talent"], (0, None))
        col = n["col"] - base
        state = "off" if not rank else ("max" if rank >= n["max"] else "on")
        icon = (
            f'<img src="{esc(icon_url(n["icon"]))}" alt="" loading="lazy" referrerpolicy="no-referrer">'
            if (n.get("icon") or "").startswith("https://") else ""
        )
        cells.append(
            f'<div class="tal {state}{" r" if col >= 2 else ""}" style="grid-row:{n["row"]};grid-column:{col + 1}" '
            f'tabindex="0" aria-label="{esc(n["name"])} {rank}/{n["max"]}">{icon}'
            f'<span class="rk">{rank}/{n["max"]}</span>{_talent_tooltip(n, rank, current)}</div>'
        )
    # Talents hors grille (positions aberrantes de l'API) : listés seulement s'ils ont des points.
    extra = [
        f'{esc(n["name"])} {ranks[n["talent"]][0]}/{n["max"]}' for n in tree["nodes"]
        if n not in in_grid and n["talent"] not in grid_talents and ranks.get(n["talent"], (0,))[0]
    ]
    icon = (
        f'<img class="ticon" src="{esc(icon_url(tree["icon"]))}" alt="" referrerpolicy="no-referrer">'
        if (tree.get("icon") or "").startswith("https://") else ""
    )
    return (
        f'<div class="tree{" zero" if not points else ""}"><div class="tree-head">{icon}<span>{esc(tree["name"])}</span>'
        f'<b>{points}</b></div><div class="tgrid">{"".join(cells)}</div>'
        + (f'<div class="extra">Aussi : {", ".join(extra)}</div>' if extra else "")
        + "</div>"
    )


def talents_html(c: Character, trees: list[dict]) -> tuple[str, str]:
    """(résumé « 0 / 0 / 14 · Magie de l'ombre », section HTML) ; vides si on ne connaît pas ses talents."""
    if c.talents is None:
        return "", ""
    groups = sorted(c.talents, key=lambda g: not g.get("active"))
    if not groups or not any(s.get("points") for g in groups for s in g.get("specs", [])):
        return "", '<p class="empty talents">Pas encore de points de talent.</p>'

    def summary(group: dict) -> str:
        if trees:
            points = talent_points(group, trees)
            main = trees[points.index(max(points))]["name"] if any(points) else ""
            return " / ".join(map(str, points)) + (f" · {main}" if main else "")
        specs = [s for s in group.get("specs", []) if s.get("points")]
        return ", ".join(f'{s.get("name")} {s.get("points")}' for s in specs)

    blocks = []
    for group in groups:
        title = ""
        if len(groups) > 1:
            title = f'<h3>{"Spé active" if group.get("active") else "Autre spé"} · {esc(summary(group))}</h3>'
        ranks = _talent_ranks(group)
        if trees:
            points = talent_points(group, trees)
            body = "".join(talent_tree_html(t, ranks, p) for t, p in zip(trees, points))
        else:  # arbres pas encore récupérés : simple liste
            body = "".join(
                f'<div class="tree"><div class="tree-head"><span>{esc(s.get("name"))}</span><b>{s.get("points")}</b></div>'
                + "".join(f'<div>{esc(t[1])} <span class="muted">{t[2]}</span></div>' for t in s.get("talents", []))
                + "</div>"
                for s in group.get("specs", []) if s.get("points")
            )
        blocks.append(f'<div class="talent-group">{title}<div class="trees">{body}</div></div>')
    # Directement sous le perso, sans titre de section : les trois arbres font partie de la fiche.
    return summary(groups[0]), f'<div class="talents">{"".join(blocks)}</div>'


def professions_table(c: Character) -> str:
    """Métiers en tableau horizontal : un en-tête par métier, le niveau et une barre en dessous.
    Principaux d'abord, séparés des secondaires par un trait plus marqué."""
    if not c.professions:
        return '<p class="empty">Aucun métier déclaré.</p>'
    ordered = sorted(c.professions.items(), key=lambda kv: (not is_primary(kv[0]), kv[0]))
    heads, cells = [], []
    for i, (p, skill) in enumerate(ordered):
        split = ' class="split"' if i and is_primary(ordered[i - 1][0]) and not is_primary(p) else ""
        heads.append(f'<th{split}><a href="/metier/{esc(p)}">{esc(profession_label(p))}</a></th>')
        pct = min(100, round(100 * skill / MAX_PROFESSION_SKILL)) if skill else 0
        cells.append(
            f'<td{split}><b>{skill if skill is not None else "?"}</b>'
            f'<div class="bar"><span style="width:{pct}%"></span></div></td>'
        )
    return (
        '<div class="table-wrap prof-wrap"><table class="prof-table">'
        f'<thead><tr>{"".join(heads)}</tr></thead><tbody><tr>{"".join(cells)}</tr></tbody></table></div>'
    )


def roles_html(c: Character) -> str:
    return ", ".join(
        f"{esc(LABELS[r])} ⭐" if r == c.preferred_role else esc(LABELS[r]) for r in roles_for(c.wow_class)
    )


SECONDARY_PROFESSIONS = [k for k, (_, primary) in PROFESSIONS.items() if not primary]


def professions_cells(c: Character) -> str:
    """Cellules de métiers d'un perso dans la liste : ses 2 principaux (nom + niveau), puis une colonne fixe par
    métier secondaire, pour que tout s'aligne d'une ligne à l'autre (case vide si le perso ne l'a pas)."""
    level = lambda skill: f"<b>{skill if skill is not None else '?'}</b>"  # noqa: E731
    primaries = sorted((p, s) for p, s in c.professions.items() if is_primary(p))
    cells = [
        f'<td class="prof"><small>{esc(profession_label(p))}</small>{level(s)}</td>' for p, s in primaries[:2]
    ]
    cells += ['<td class="prof"><span class="none">—</span></td>'] * (2 - len(cells))
    for i, p in enumerate(SECONDARY_PROFESSIONS):
        value = level(c.professions[p]) if p in c.professions else '<span class="none">—</span>'
        cells.append(f'<td class="sec{" split" if i == 0 else ""}">{value}</td>')
    return "".join(cells)


def _item_tooltip(item: dict, top: list[str]) -> str:
    color = QUALITY_COLORS.get(item.get("quality") or "", "#fff")
    lines = []
    for kind, text in item.get("lines", []):
        tokens = gear.line_tokens(text) if kind in ("stat", "enchant") else []
        prio = " prio" if kind == "stat" and set(tokens) & set(top) else ""
        data = f' data-t="{esc(" ".join(tokens))}"' if tokens else ""
        lines.append(f'<div class="{esc(kind)}{prio}"{data}>{esc(text)}</div>')
    ilvl = f'<div class="ilvl">Niveau d\'objet {item["ilvl"]}</div>' if item.get("ilvl") else ""
    return f'<div class="tt"><b style="color:{color}">{esc(item["name"])}</b>{ilvl}{"".join(lines)}</div>'


def slot_html(slot: str, item: dict | None, icons: dict[int, str], top: list[str]) -> str:
    label = gear.SLOT_LABELS.get(slot, slot)
    if not item:
        return f'<div class="slot empty"><span class="ph"></span><div class="txt"><div class="sb">{esc(label)}</div></div></div>'
    icon = icons.get(item.get("id"))
    img = (
        f'<img src="{esc(icon_url(icon))}" alt="" loading="lazy" referrerpolicy="no-referrer"'
        f' style="border-color:{QUALITY_COLORS.get(item.get("quality") or "", "#4a4a4a")}">'
        if icon and icon.startswith("https://") else
        f'<span class="ph" style="border-color:{QUALITY_COLORS.get(item.get("quality") or "", "#4a4a4a")}"></span>'
    )
    tokens = sorted({t for k, text in item.get("lines", []) if k == "stat" for t in gear.line_tokens(text)})
    prio = " prio" if set(tokens) & set(top) else ""
    color = QUALITY_COLORS.get(item.get("quality") or "", "inherit")
    sub = esc(label) + (f" · {item['ilvl']}" if item.get("ilvl") else "")
    return (
        f'<div class="slot{prio}" tabindex="0" data-t="{esc(" ".join(tokens))}">{img}<div class="txt">'
        f'<div class="nm" style="color:{color}">{esc(item["name"])}</div><div class="sb">{sub}</div></div>'
        f"{_item_tooltip(item, top)}</div>"
    )


# (titre, [(clé, libellé, pourcentage ?)]) du panneau de caractéristiques.
STAT_GROUPS = (
    ("Général", (("health", "Santé", False), ("power", None, False), ("armor", "Armure", False))),
    ("Attributs", (("strength", "Force", False), ("agility", "Agilité", False), ("stamina", "Endurance", False),
                   ("intellect", "Intelligence", False), ("spirit", "Esprit", False))),
    ("Mêlée", (("attack_power", "Puissance d'attaque", False), ("melee_hit", "Toucher", True),
               ("melee_crit", "Critique", True), ("melee_haste", "Hâte", True), ("expertise", "Expertise", False),
               ("main_hand_dps", "DPS de l'arme", False))),
    ("Distance", (("ranged_attack_power", "Puissance d'attaque", False), ("ranged_hit", "Toucher", True),
                  ("ranged_crit", "Critique", True), ("ranged_haste", "Hâte", True))),
    ("Sorts", (("spell_power", "Puissance des sorts", False), ("spell_healing", "Puissance des soins", False),
               ("spell_hit", "Toucher", True), ("spell_crit", "Critique", True), ("spell_haste", "Hâte", True),
               ("mana_regen_combat", "Mana / 5 s en combat", False))),
    ("Défense", (("defense", "Défense", False), ("dodge", "Esquive", True), ("parry", "Parade", True),
                 ("block", "Blocage", True))),
)
ALWAYS_SHOWN = {"health", "power", "armor", "strength", "agility", "stamina", "intellect", "spirit"}

# À quoi sert chaque caractéristique (infobulle du panneau). Volontairement sans chiffres précis quand
# Forever peut différer de Classic.
STAT_HELP = {
    "health": "Les points de vie : à 0, le perso meurt. Ils viennent surtout de l'Endurance.",
    "armor": "Réduit les dégâts physiques subis (coups, flèches). Aucun effet contre la magie. "
             "Vient surtout de l'équipement, et un peu de l'Agilité.",
    "strength": "Augmente la puissance d'attaque en mêlée, donc les dégâts des armes et des techniques physiques. "
                "Augmente aussi les dégâts absorbés quand on bloque avec un bouclier.",
    "agility": "Augmente les chances de coup critique et d'esquive, ainsi que l'armure. Donne de la puissance "
               "d'attaque à distance, et aussi en mêlée pour les Voleurs, les Chasseurs et les Druides en forme de félin.",
    "stamina": "Augmente les points de vie. C'est la stat de survie : indispensable pour les tanks, utile à tout le monde.",
    "intellect": "Augmente la réserve de mana et les chances de coup critique des sorts.",
    "spirit": "Accélère la régénération de vie et de mana. Pour le mana, elle ne joue qu'après 5 secondes "
              "sans lancer de sort : c'est la récupération entre deux combats.",
    "attack_power": "Augmente les dégâts des attaques et techniques de mêlée. Vient de la Force (et de l'Agilité "
                    "pour certaines classes) et de l'équipement.",
    "melee_hit": "Réduit le risque de rater sa cible en mêlée. Contre un boss, inutile au-delà du cap affiché.",
    "melee_crit": "Chance qu'une attaque de mêlée soit un coup critique, qui inflige le double de dégâts.",
    "melee_haste": "Accélère la vitesse d'attaque : plus de coups par seconde.",
    "expertise": "Réduit les chances que la cible esquive ou pare vos attaques de mêlée.",
    "main_hand_dps": "Dégâts moyens par seconde de l'arme tenue en main droite.",
    "ranged_attack_power": "Augmente les dégâts des armes à distance (arcs, fusils, arbalètes) et des techniques "
                           "à distance. Vient surtout de l'Agilité et de l'équipement.",
    "ranged_hit": "Réduit le risque de rater sa cible à distance. Contre un boss, inutile au-delà du cap affiché.",
    "ranged_crit": "Chance qu'un tir soit un coup critique, qui inflige le double de dégâts.",
    "ranged_haste": "Accélère la vitesse de tir.",
    "spell_power": "Augmente les dégâts infligés par les sorts.",
    "spell_healing": "Augmente les points de vie rendus par les sorts de soin.",
    "spell_hit": "Réduit le risque qu'un sort soit résisté (raté). Contre un boss, inutile au-delà du cap affiché.",
    "spell_crit": "Chance qu'un sort de dégâts ou de soin soit critique, pour un effet nettement plus fort.",
    "spell_haste": "Réduit le temps d'incantation des sorts.",
    "mana_regen_combat": "Mana récupéré toutes les 5 secondes, même en lançant des sorts. Précieux pour les "
                         "soigneurs sur les longs combats.",
    "defense": "Réduit les chances d'être touché et de subir un coup critique, et augmente esquive, parade et "
               "blocage. La stat clé des tanks, qui doivent éviter les coups critiques des boss.",
    "dodge": "Chance d'esquiver complètement une attaque de mêlée.",
    "parry": "Chance de parer une attaque de mêlée venant de face (aucun dégât).",
    "block": "Chance de bloquer une attaque avec un bouclier, ce qui réduit les dégâts reçus.",
}
POWER_HELP = {
    "mana": "La ressource des sorts. Le mana max vient de l'Intelligence ; il se régénère grâce à l'Esprit et au "
            "mana / 5 s.",
    "rage": "Se gagne en frappant et en recevant des coups, et redescend hors combat. Sert à lancer les techniques.",
    "energie": "Se recharge vite et en continu. Elle limite le nombre de techniques qu'on peut enchaîner.",
}
POWER_HELP["energy"] = POWER_HELP["energie"]  # au cas où l'API répond en anglais
# Remarques propres à la classe du perso : (caractéristique, classes concernées, texte).
CASTERS = frozenset({"mage", "pretre", "demoniste"})
NO_MANA = frozenset({"guerrier", "voleur"})
CLASS_NOTES = (
    ("strength", CASTERS, "Inutile ou presque pour cette classe, qui se bat avec ses sorts."),
    ("strength", frozenset({"guerrier", "paladin", "chaman", "druide"}),
     "Très efficace pour cette classe en mêlée : chaque point de Force donne plus de puissance d'attaque."),
    ("agility", CASTERS, "Peu utile pour cette classe : un peu d'armure et de critique en mêlée seulement."),
    ("agility", frozenset({"voleur", "chasseur"}), "Une des stats principales de cette classe."),
    ("intellect", NO_MANA, "Inutile pour cette classe, qui n'a pas de mana."),
    ("spirit", NO_MANA, "Pour cette classe (sans mana), ne sert qu'à récupérer de la vie hors combat."),
)


def stat_tooltip(key: str, label: str, wow_class: str) -> str:
    """Infobulle d'une ligne du panneau : à quoi sert la caractéristique, plus une remarque selon la classe."""
    if key == "power":
        text = POWER_HELP.get(normalize(label), "La ressource utilisée pour lancer les techniques.")
    else:
        text = STAT_HELP.get(key)
    if not text:
        return ""
    notes = "".join(
        f'<p class="note">{esc(class_label(wow_class))} : {esc(note)}</p>'
        for stat, classes, note in CLASS_NOTES
        if stat == key and wow_class in classes
    )
    return f'<div class="tt"><b>{esc(label)}</b><p>{esc(text)}</p>{notes}</div>'


def _num(value: float, pct: bool) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".") if pct else f"{value:.0f}" if value == int(value) else f"{value:.1f}"
    return text.replace(".", ",") + (" %" if pct else "")


def _prio_box(spec: str, view: dict, chosen: bool) -> str:
    name, kind, tokens = gear.PRIORITIES[spec]
    cap = gear.hit_cap(kind)
    chips, top = [], 0
    for token in tokens:
        label = gear.TOKENS[token][0] + (f" (cap {cap:.0f} %)" if token == "hit" and cap else "")
        done = token == "hit" and bool(view["capped"])
        cls = "done" if done else ("top" if top < 3 else "")
        top += 0 if done else 1
        chips.append(f'<span class="chip {cls}">{esc(label)}</span>')
    return f'<div class="chips" data-spec="{spec}"{"" if chosen else " hidden"}>{"".join(chips)}</div>'


def stats_html(c: Character, spec: str | None, guessed: bool = False) -> str:
    """Caractéristiques, avec les stats à pousser pour la spé ; un menu permet de voir les autres spés de la classe
    (le changement se fait dans la page, voir SPEC_SCRIPT)."""
    stats = c.stats or {}
    specs = [x for x in gear.CLASS_SPECS.get(c.wow_class, ()) if x in gear.PRIORITIES]
    views = {x: gear.spec_view(x, stats) for x in specs}
    view = views.get(spec) or {"ranks": {}, "capped": None, "top": []}
    any_ranked = {k for v in views.values() for k in v["ranks"]}

    prio = ""
    if specs and spec in views:
        options = "".join(
            f'<option value="{x}"{" selected" if x == spec else ""}>{esc(gear.PRIORITIES[x][0])}</option>' for x in specs
        )
        hint = " <span class=\"muted\">(d'après son rôle, talents inconnus)</span>" if guessed else ""
        prio = (
            f'<div class="prio-box">Stats à pousser en <select id="spec" aria-label="Spé">{options}</select>{hint}, '
            "dans l'ordre :" + "".join(_prio_box(x, views[x], x == spec) for x in specs) + "</div>"
        )

    groups = []
    for title, rows in STAT_GROUPS:
        cells = []
        for key, label, pct in rows:
            value = stats.get(key)
            if value is None or (not value and key not in ALWAYS_SHOWN and key not in any_ranked):
                continue
            label = label or stats.get("power_name") or "Énergie"
            rank = view["ranks"].get(key)
            capped = key == view["capped"]
            css = f" p{rank}" if rank and rank <= 3 and not capped else ""
            css += " capped" if capped else ""
            cap = gear.hit_cap(key.split("_")[0]) if key.endswith("_hit") else None
            shown = _num(value, pct) + (f" / {cap:.0f} %" if cap else "")
            tooltip = stat_tooltip(key, label, c.wow_class)
            focus = ' tabindex="0"' if tooltip else ""  # tabindex : l'infobulle s'ouvre aussi au toucher
            cells.append(
                f'<div class="srow{css}" data-k="{key}"{focus}><i>{rank or ""}</i><span>{esc(label)}</span>'
                f"<b>{esc(shown)}</b>{tooltip}</div>"
            )
        if cells:
            groups.append(f"<h4>{esc(title)}</h4>{''.join(cells)}")
    if not groups and not prio:
        return ""
    checked = (
        f", vérifié le {datetime.fromtimestamp(gear.SOURCE_CHECKED_AT).strftime('%d/%m/%Y')}"
        if gear.SOURCE_CHECKED_AT else ""
    )
    source = (
        f'<p class="src">Priorités : <a href="{statsource.SOURCE_URL}" rel="noopener">guide WoW Forever de '
        f"stillsixty.com</a>{checked}, relu chaque nuit. Le toucher compte jusqu'au cap contre un boss, ensuite "
        "on passe à la suite.</p>" if prio else ""
    )
    data = f'<script type="application/json" id="spec-data">{json.dumps(views)}</script>' if prio else ""
    help_line = '<p class="help">Survole ou touche une caractéristique pour savoir à quoi elle sert.</p>'
    return (
        f'<aside class="statbox"><h3>Caractéristiques</h3>{help_line}{prio}{"".join(groups)}{source}{data}</aside>'
    )


def armory_html(c: Character, spec: str | None, icons: dict[int, str], below: str = "", guessed: bool = False) -> str:
    """Fiche façon jeu : objets autour du rendu, caractéristiques à côté. Vide sans équipement connu."""
    if not c.equipment:
        return ""
    by_slot = {i["slot"]: i for i in c.equipment}
    top = list(gear.PRIORITIES[spec][2][:3]) if spec in gear.PRIORITIES else []
    column = lambda slots: "".join(slot_html(s, by_slot.get(s), icons, top) for s in slots)  # noqa: E731
    render = ""
    if c.render_url and c.render_url.startswith("https://"):
        render = (
            f'<div class="frame"><img src="{esc(c.render_url)}" alt="{esc(c.name)}" referrerpolicy="no-referrer"></div>'
        )
    return (
        f'<div class="armory"><div class="main"><section class="doll"><div class="slots left">{column(gear.LEFT_SLOTS)}</div>'
        f'<div class="center">{render}</div><div class="slots right">{column(gear.RIGHT_SLOTS)}</div>'
        f'<div class="weapons">{column(gear.WEAPON_SLOTS)}</div></section>{below}</div>{stats_html(c, spec, guessed)}</div>'
    )


# Équipement fabricable : objets jusqu'à N niveaux au-dessus du perso (« bientôt »), au plus N par emplacement.
GEAR_LEVEL_AHEAD = 5
GEAR_PER_SLOT = 12
GEAR_GROUP_LABELS = {"FINGER_1": "Anneaux", "TRINKET_1": "Bijoux", "MAIN_HAND": "Armes", "OFF_HAND": "Main gauche"}


def crafted_gear_html(
    c: Character, recipes: list[GuildRecipe], crafters: dict[int, list[Crafter]], viewer_id: int | None,
    top: list[str],
) -> str:
    """Objets que les persos du serveur savent fabriquer et que ce perso peut porter (classe, niveau), par
    emplacement, avec l'objet porté pour comparer et qui sait le faire. Vide s'il n'y en a aucun."""
    equipped = {i["slot"]: i for i in c.equipment or []}
    groups: dict[str, list[tuple[GuildRecipe, int]]] = {}
    for recipe in recipes:
        item = recipe.item
        from_level = proficiency.usable_from(c.wow_class, item)
        if from_level is None or (c.level and from_level > c.level + GEAR_LEVEL_AHEAD):
            continue
        slots = proficiency.EQUIP_SLOTS.get((item or {}).get("slot") or "")
        if slots:
            groups.setdefault(slots[0], []).append((recipe, from_level))
    if not groups:
        return ""

    def worn_ilvl(slot: str) -> int | None:
        """Niveau d'objet le plus faible porté sur ces emplacements (0 : un emplacement est vide)."""
        levels = [(equipped.get(s) or {}).get("ilvl") for s in proficiency.EQUIP_SLOTS_OF_GROUP.get(slot, (slot,))]
        if not equipped:
            return None
        return min((lv or 0) for lv in levels)

    html_groups, total = [], 0
    for slot in sorted(groups, key=lambda s: proficiency.SLOT_ORDER.index(s) if s in proficiency.SLOT_ORDER else 99):
        worn = worn_ilvl(slot)
        entries = []
        for recipe, from_level in groups[slot]:
            item = recipe.item or {}
            tokens = {t for k, text in item.get("lines", []) if k == "stat" for t in gear.line_tokens(text)}
            ilvl = item.get("ilvl")
            up = worn is not None and isinstance(ilvl, int) and ilvl > worn
            later = bool(c.level and from_level > c.level)
            entries.append((later, -(ilvl or 0), -len(tokens & set(top)), recipe, from_level, up))
        entries.sort(key=lambda e: e[:3])
        cards = []
        for later, _, _, recipe, from_level, up in entries[:GEAR_PER_SLOT]:
            item = recipe.item or {}
            kind = proficiency.item_kind(item)
            color = QUALITY_COLORS.get(item.get("quality") or "", "inherit")
            meta = [proficiency.kind_label(kind) if kind else ""]
            if item.get("ilvl"):
                meta.append(f"niv. d'objet {item['ilvl']}")
            meta.append(f"à partir du niveau {from_level}" if later else f"niv. {from_level}+")
            lines = "".join(
                f'<div class="{esc(k)}{" prio" if k == "stat" and set(gear.line_tokens(text)) & set(top) else ""}">'
                f"{esc(text)}</div>"
                for k, text in item.get("lines", []) if k in ("stat", "effect", "armor", "weapon")
            )
            makers = crafters.get(recipe.id, [])
            mine = viewer_id is not None and any(m.user_id == viewer_id for m in makers)
            others = [m for m in makers if m.user_id != viewer_id]
            who = ", ".join(f'<a href="/perso/{m.character_id}">{esc(m.name)}</a>' for m in makers) or "?"
            action = ""
            if viewer_id is not None and others:
                action = f' · <a class="order-link" href="/atelier?recette={recipe.id}">🛒 Commander</a>'
            elif mine:
                action = " · tu sais le fabriquer"
            badges = ('<span class="gbadge up">▲ mieux que l\'objet porté</span>' if up else "") + (
                '<span class="gbadge later">bientôt</span>' if later else ""
            )
            cards.append(
                f'<div class="gear-item{" later" if later else ""}" data-up="{int(up)}">'
                f'<div class="gi-head"><b style="color:{color}">{esc(recipe.name)}</b>{badges}</div>'
                f'<div class="gi-meta">{esc(" · ".join(m for m in meta if m))}</div>'
                f'<div class="tip">{lines}</div><div class="gi-who">🔨 {who}{action}</div></div>'
            )
        total += len(cards)
        label = GEAR_GROUP_LABELS.get(slot) or gear.SLOT_LABELS.get(slot, slot)
        current = [equipped[s] for s in proficiency.EQUIP_SLOTS_OF_GROUP.get(slot, (slot,)) if s in equipped]
        worn_text = ", ".join(
            f'{esc(i["name"])}' + (f' ({i["ilvl"]})' if i.get("ilvl") else "") for i in current
        ) or "rien"
        more = len(entries) - GEAR_PER_SLOT
        more_text = f'<p class="muted">… et {more} autre(s), de plus bas niveau.</p>' if more > 0 else ""
        html_groups.append(
            f'<div class="gear-group"><h4>{esc(label)} <small class="muted">· porté : {worn_text}</small></h4>'
            f'<div class="gear-list">{"".join(cards)}</div>{more_text}</div>'
        )

    level = f"jusqu'au niveau {c.level + GEAR_LEVEL_AHEAD} " if c.level else ""
    return f"""<details class="fold big" data-keep id="equipement-fabricable"><summary><span>🛠️ Équipement fabricable par
la guilde</span><span class="n">{total}</span></summary><div class="fold-body">
<p class="muted">Objets que les persos du serveur savent fabriquer et qu'un {esc(class_label(c.wow_class))} peut porter
{level}(armure, armes, bijoux), triés par niveau d'objet ; ★ les stats prioritaires de la spé. Les mailles et plaques
s'apprennent au niveau 40 ; certaines armes chez un maître d'armes.</p>
<label class="gear-only"><input type="checkbox" id="gear-only-up"> Seulement ce qui améliore l'équipement porté</label>
<div class="gear-groups">{"".join(html_groups)}</div></div></details>"""


