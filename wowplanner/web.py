"""Petit site web public, en lecture seule : persos, métiers et recettes du serveur.

Aucune info personnelle : ni pseudo Discord, ni identifiant Discord, ni BattleTag, et rien qui
permette de relier deux persos au même joueur. Seuls les persos (nom, classe, race, rôles),
leurs métiers et leurs recettes sont affichés.

Servi par aiohttp dans le même processus que le bot (même base SQLite, lue seulement). Activé
par WEB_PORT ; derrière Traefik en production (voir docker-compose.traefik.yml).
"""
from __future__ import annotations

import html
import logging
from datetime import datetime
from typing import Callable

from aiohttp import web

from .db import Character, Database, GuildRecipe
from .gamedata import CLASSES, PROFESSIONS, class_label, is_primary, profession_label, race_label, roles_for
from .recipes import crafted_by_map, expand_reagents, filter_recipes, group_by_family, normalize
from .roles import LABELS, ROLES

log = logging.getLogger(__name__)

CLASS_COLORS = {
    "guerrier": "#C79C6E", "paladin": "#F58CBA", "chasseur": "#ABD473", "voleur": "#FFF569", "pretre": "#FFFFFF",
    "chaman": "#3A8EF0", "mage": "#69CCF0", "demoniste": "#9482C9", "druide": "#FF7D0A",
}


# Couleurs de qualité des objets (éclaircies quand le bleu/violet du jeu est illisible sur fond sombre).
QUALITY_COLORS = {
    "POOR": "#9d9d9d", "UNCOMMON": "#1eff00", "RARE": "#4a9dff", "EPIC": "#b56bff", "LEGENDARY": "#ff8000",
    "ARTIFACT": "#e6cc80", "HEIRLOOM": "#00ccff",
}


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


# Thèmes : Alliance (par défaut) et une capitale par race de l'Alliance. Tout passe par des
# variables CSS ; le choix est mémorisé dans le navigateur du visiteur (localStorage).
THEMES = {
    "alliance": "Alliance",
    "humain": "Humain · Hurlevent",
    "nain": "Nain · Forgefer",
    "elfe_nuit": "Elfe de la nuit · Darnassus",
    "gnome": "Gnome · Gnomeregan",
}
DEFAULT_THEME = "alliance"

STYLE = """
:root, [data-theme="alliance"] {
  --bg:#0a1222; --glow:rgba(40,90,190,.35); --panel:#111d36; --panel2:#182848; --text:#e9edf6;
  --muted:#98a8c6; --accent:#f2c75c; --line:#253a62; --head1:#16336b; --head2:#0b1a3c; --crest:"🛡️";
}
[data-theme="humain"] {
  --bg:#12161d; --glow:rgba(70,110,180,.28); --panel:#1b212b; --panel2:#232b38; --text:#eef0f3;
  --muted:#a3abb8; --accent:#e9c46a; --line:#323c4c; --head1:#1f4f9a; --head2:#163a73; --crest:"🦁";
}
[data-theme="nain"] {
  --bg:#15100c; --glow:rgba(255,120,40,.20); --panel:#211912; --panel2:#2c2118; --text:#f2e8dc;
  --muted:#b9a58e; --accent:#ff9447; --line:#45331f; --head1:#5a3417; --head2:#2a180b; --crest:"⚒️";
}
[data-theme="elfe_nuit"] {
  --bg:#0e0b1a; --glow:rgba(140,110,255,.28); --panel:#18142b; --panel2:#211b3b; --text:#eeeaf9;
  --muted:#a69fc7; --accent:#8ee6d8; --line:#352c5a; --head1:#3b2a72; --head2:#1a1340; --crest:"🌙";
}
[data-theme="gnome"] {
  --bg:#0b1716; --glow:rgba(60,220,190,.20); --panel:#122321; --panel2:#18302d; --text:#e4f5f1;
  --muted:#8fb6ad; --accent:#ff74d4; --line:#244340; --head1:#16534c; --head2:#0b2a27; --crest:"⚙️";
}
* { box-sizing:border-box; }
[hidden] { display:none !important; }
body { margin:0; color:var(--text); min-height:100vh;
       background:radial-gradient(ellipse 90% 50% at 50% 0, var(--glow), transparent 70%) fixed, var(--bg);
       font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }
a { color:inherit; text-decoration:none; }
a:hover { text-decoration:underline; }
.title { font-family:"Cinzel","Trajan Pro","Palatino Linotype",Palatino,"Book Antiqua",Georgia,serif; }
header { background:linear-gradient(180deg,var(--head1),var(--head2)); border-bottom:2px solid var(--accent);
         box-shadow:0 2px 12px rgba(0,0,0,.45); padding:10px 16px; display:flex; gap:20px; align-items:center;
         flex-wrap:wrap; position:sticky; top:0; z-index:5; }
header .brand { font-weight:700; color:var(--accent); font-size:19px; letter-spacing:.04em; }
header .brand::before { content:var(--crest); margin-right:8px; }
header nav { display:flex; gap:16px; }
header nav a { color:var(--muted); }
header nav a.active { color:var(--text); font-weight:600; border-bottom:2px solid var(--accent); }
header .theme { margin-left:auto; }
header select { background:rgba(0,0,0,.25); color:var(--text); border:1px solid var(--accent); border-radius:8px;
                padding:5px 8px; font:inherit; font-size:13px; }
header select option { background:var(--panel); }
main { max-width:1200px; margin:0 auto; padding:20px 16px 48px; }
h1 { margin:0 0 4px; font-size:28px; }
h2 { margin:28px 0 10px; font-size:19px; color:var(--accent); }
.sub { color:var(--muted); margin:0 0 16px; }
.filters { display:flex; gap:8px; flex-wrap:wrap; margin:12px 0 16px; }
.filters input, .filters select, .filters button { background:var(--panel); color:var(--text);
  border:1px solid var(--line); border-radius:8px; padding:8px 10px; font:inherit; }
.filters input { flex:1 1 220px; }
.filters button { cursor:pointer; }
.filters button:hover, .filters input:focus, .filters select:focus { border-color:var(--accent); outline:none; }
.table-wrap { overflow-x:auto; border:1px solid var(--line); border-radius:10px; background:var(--panel); }
table { width:100%; border-collapse:collapse; }
th, td { text-align:left; padding:9px 12px; border-bottom:1px solid var(--line); vertical-align:top; }
th { background:var(--panel2); color:var(--accent); font-weight:600; font-size:13px; white-space:nowrap; }
tr:last-child td { border-bottom:none; }
tbody tr:hover { background:var(--panel2); }
.num { text-align:right; font-variant-numeric:tabular-nums; }
.tag { display:inline-block; background:var(--panel2); border:1px solid var(--line); border-radius:999px;
       padding:1px 9px; margin:2px 4px 2px 0; font-size:13px; white-space:nowrap; }
.tag b { font-variant-numeric:tabular-nums; color:var(--accent); }
.muted { color:var(--muted); }
details.fold { border:1px solid var(--line); border-radius:10px; background:var(--panel); margin:8px 0; }
details.fold > summary { cursor:pointer; list-style:none; padding:10px 14px; display:flex; align-items:center;
  gap:10px; color:var(--accent); font-weight:600; text-transform:uppercase; letter-spacing:.06em; font-size:14px;
  user-select:none; border-radius:10px; }
details.fold > summary::-webkit-details-marker { display:none; }
details.fold > summary::before { content:"▸"; transition:transform .15s; }
details.fold[open] > summary::before { transform:rotate(90deg); }
details.fold > summary:hover { background:var(--panel2); }
details.fold > summary .n { margin-left:auto; color:var(--muted); font-weight:400; font-size:12px;
  background:var(--panel2); border:1px solid var(--line); border-radius:999px; padding:0 9px; }
details.fold > .fold-body { padding:4px 12px 12px; }
details.fold.big { background:transparent; border:none; margin:18px 0 6px; }
details.fold.big > summary { font-size:19px; text-transform:none; letter-spacing:.02em; padding:6px 2px;
  border-bottom:1px solid var(--line); border-radius:0; }
details.fold.big > summary:hover { background:transparent; }
details.fold.big > .fold-body { padding:6px 0 0; }
.cards { display:grid; grid-template-columns:repeat(auto-fill,minmax(250px,1fr)); gap:10px; }
.card { background:var(--panel2); border:1px solid var(--line); border-top:2px solid var(--accent);
        border-radius:10px; padding:10px 12px; }
.card h4 { margin:0 0 6px; font-size:15px; }
.card ul { list-style:none; margin:0; padding:0; }
.card li { padding:1px 0; }
.card li.d1 { padding-left:18px; color:var(--muted); }
.card li.d2 { padding-left:36px; color:var(--muted); }
.card li.d3 { padding-left:54px; color:var(--muted); }
.card li.d1::before, .card li.d2::before, .card li.d3::before { content:"↳ "; }
.card .who { margin-top:6px; font-size:13px; color:var(--muted); }
.tip { font-size:13px; line-height:1.4; margin:0 0 8px; padding:0 0 8px; border-bottom:1px dashed var(--line); }
.tip .type, .tip .bind, .tip .req { color:var(--muted); }
.tip .effect { color:#3ee05a; }
.tip .flavor { color:#e6c35c; font-style:italic; }
.tip .req { font-size:12px; }
.card .who a { color:var(--text); }
.grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(200px,1fr)); gap:10px; }
.tile { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:14px; display:block;
        transition:border-color .15s, transform .15s; }
.tile:hover { border-color:var(--accent); text-decoration:none; transform:translateY(-2px); }
.tile .big { font-size:20px; font-weight:700; color:var(--accent); }
.empty { color:var(--muted); font-style:italic; }
.who-cell { display:flex; align-items:center; gap:10px; }
.avatar { width:34px; height:34px; border-radius:50%; object-fit:cover; border:2px solid var(--line); flex:none;
          background:var(--panel2); }
.avatar.none { display:inline-flex; align-items:center; justify-content:center; font-size:16px; }
.hero { display:flex; gap:24px; align-items:flex-end; justify-content:space-between; flex-wrap:wrap; }
.hero .info { flex:1 1 320px; min-width:0; }
.hero .render { flex:0 1 360px; max-width:100%; text-align:center; position:relative; }
.hero .render::before { content:""; position:absolute; inset:15% 5% 0; border-radius:50%;
  background:radial-gradient(closest-side, var(--glow), transparent); z-index:-1; }
/* Le rendu Blizzard fait 1600×1200 avec le perso au centre-bas : on garde la zone x 25–75 %, y 25–87 %. */
.hero .render .frame { width:100%; aspect-ratio:1 / .93; overflow:hidden; }
.hero .render img { display:block; width:200%; max-width:none; margin:-37.5% 0 0 -50%;
  filter:drop-shadow(0 8px 18px rgba(0,0,0,.6)); }
@media (max-width:700px) { .hero { flex-direction:column-reverse; align-items:stretch; }
  .hero .render { width:min(300px, 100%); margin:0 auto; } }
/* Arbres de talents façon jeu : grille 4 colonnes, infobulle au survol (ou au toucher sur mobile). */
.talent-group h3 { margin:14px 0 8px; font-size:15px; color:var(--muted); font-weight:600; }
.trees { display:flex; flex-wrap:wrap; gap:16px; align-items:flex-start; }
.tree { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:10px 12px 14px; }
.tree-head { display:flex; align-items:center; gap:8px; margin-bottom:10px; font-weight:700; }
.tree-head b { margin-left:auto; padding-left:12px; color:var(--accent); font-size:18px; }
.tree.zero .tree-head b { color:var(--muted); }
.ticon { width:26px; height:26px; border-radius:5px; border:1px solid var(--line); }
.tgrid { --ts:44px; display:grid; grid-template-columns:repeat(4, var(--ts)); grid-auto-rows:var(--ts); gap:10px; }
.tal { position:relative; width:var(--ts); height:var(--ts); border-radius:7px; border:2px solid #4a4a4a;
       background:var(--panel2); cursor:help; }
.tal img { display:block; width:100%; height:100%; border-radius:5px; }
.tal.off img { filter:grayscale(1) brightness(.5); }
.tal.on { border-color:#3ee05a; box-shadow:0 0 6px rgba(62,224,90,.35); }
.tal.max { border-color:#f2c75c; box-shadow:0 0 6px rgba(242,199,92,.4); }
.tal .rk { position:absolute; right:-7px; bottom:-7px; background:#111; color:#3ee05a; font-size:11px;
           font-weight:700; line-height:16px; padding:0 4px; border-radius:6px; border:1px solid #444; }
.tal.max .rk { color:#f2c75c; }
.tal.off .rk { color:#8a8a8a; }
.tal .tt { display:none; position:absolute; top:calc(100% + 9px); left:-4px; width:260px; z-index:20;
           background:rgba(10,13,22,.97); color:#eee; border:1px solid #6a5a32; border-radius:8px; padding:8px 10px;
           font-size:13px; line-height:1.4; box-shadow:0 6px 22px rgba(0,0,0,.65); cursor:auto; text-align:left; }
.tal.r .tt { left:auto; right:-4px; }
.tal:hover .tt, .tal:focus .tt { display:block; }
.tal:focus { outline:2px solid var(--accent); outline-offset:2px; }
.tt b { color:#fff; font-size:14px; }
.tt .lvl { color:#9a9a9a; font-size:12px; }
.tt .meta { color:#c8c8c8; }
.tt .desc { color:#f2c75c; margin-top:2px; }
.tt .next { margin-top:6px; color:#9a9a9a; }
.tt .next span { display:block; color:#f2c75c; }
.tree .extra { margin-top:10px; font-size:13px; color:var(--muted); max-width:206px; }
@media (max-width:420px) { .tgrid { --ts:38px; gap:8px; } .tal .tt { width:220px; } }
footer { color:var(--muted); font-size:12px; text-align:center; padding:24px; }
@media (max-width:600px) { header .theme { margin-left:0; width:100%; } header select { width:100%; } }
"""

# Appliqué dans <head> pour éviter un flash du thème par défaut.
THEME_BOOT = (
    "<script>try{const t=localStorage.getItem('wp-theme');"
    f"if({list(THEMES)!r}.includes(t))document.documentElement.dataset.theme=t;}}catch(e){{}}</script>"
)

THEME_SCRIPT = """
<script>
(() => {
  const sel = document.getElementById("theme");
  sel.value = document.documentElement.dataset.theme || sel.options[0].value;
  sel.addEventListener("change", () => {
    document.documentElement.dataset.theme = sel.value;
    try { localStorage.setItem("wp-theme", sel.value); } catch (e) {}
  });
})();
</script>
"""

FILTER_SCRIPT = """
<script>
(() => {
  const norm = s => s.normalize("NFD").replace(/[\\u0300-\\u036f]/g, "").toLowerCase();
  const q = document.getElementById("q");
  const selects = [...document.querySelectorAll("select[data-filter]")];
  const items = [...document.querySelectorAll("[data-search]")];
  const sections = [...document.querySelectorAll("[data-section]")];
  const folds = [...document.querySelectorAll("details.fold:not([data-keep])")];
  folds.forEach(d => d.dataset.default = d.open ? "1" : "");
  const count = document.getElementById("count");
  const preset = new URLSearchParams(location.search).get("q");
  if (q && preset) q.value = preset;
  let searching = false;
  function apply() {
    const text = q ? norm(q.value.trim()) : "";
    let shown = 0;
    for (const el of items) {
      let ok = !text || el.dataset.search.includes(text);
      for (const s of selects) {
        if (s.value && !(el.dataset[s.dataset.filter] || "").split(" ").includes(s.value)) ok = false;
      }
      el.hidden = !ok;
      if (ok) shown++;
    }
    for (const sec of sections) {
      const n = sec.querySelectorAll("[data-search]:not([hidden])").length;
      sec.hidden = !n;
      const badge = sec.querySelector(":scope > summary .n");
      if (badge) badge.textContent = n;
    }
    // Pendant une recherche on déplie ce qui correspond ; en l'effaçant on revient à l'état initial.
    if (text) folds.forEach(d => { if (!d.hidden) d.open = true; });
    else if (searching) folds.forEach(d => d.open = !!d.dataset.default);
    searching = !!text;
    if (count) count.textContent = shown;
  }
  if (q) q.addEventListener("input", apply);
  selects.forEach(s => s.addEventListener("change", apply));
  document.querySelectorAll("button[data-fold]").forEach(b => b.addEventListener("click", () => {
    const open = b.dataset.fold === "open";
    folds.forEach(d => { if (!d.hidden) d.open = open; });
  }));
  apply();
})();
</script>
"""

FOLD_BUTTONS = (
    '<button type="button" data-fold="open">Tout déplier</button>'
    '<button type="button" data-fold="close">Tout replier</button>'
)


def page(title: str, active: str, body: str, scripts: str = "") -> web.Response:
    nav = "".join(
        f'<a href="{href}" class="{"active" if key == active else ""}">{label}</a>'
        for key, href, label in (("persos", "/", "Persos"), ("metiers", "/metiers", "Métiers"))
    )
    themes = "".join(f'<option value="{k}">{esc(v)}</option>' for k, v in THEMES.items())
    document = f"""<!doctype html>
<html lang="fr" data-theme="{DEFAULT_THEME}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} · WoW Planner</title>{THEME_BOOT}<style>{STYLE}</style></head>
<body><header><a class="brand title" href="/">WoW Planner</a><nav>{nav}</nav>
<label class="theme" title="Thème d'affichage"><select id="theme" aria-label="Thème">{themes}</select></label></header>
<main>{body}</main>
<footer>Données des persos déclarés sur le Discord, complétées par l'armurerie Blizzard (WoW Forever).</footer>
{THEME_SCRIPT}{scripts}</body></html>"""
    return web.Response(text=document, content_type="text/html")


def class_span(c: Character) -> str:
    return f'<span style="color:{CLASS_COLORS.get(c.wow_class, "inherit")}">{esc(class_label(c.wow_class))}</span>'


def avatar_html(c: Character) -> str:
    if c.avatar_url and c.avatar_url.startswith("https://"):
        return f'<img class="avatar" src="{esc(c.avatar_url)}" alt="" loading="lazy" referrerpolicy="no-referrer">'
    return '<span class="avatar none">👤</span>'


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
            f'<img src="{esc(n["icon"])}" alt="" loading="lazy" referrerpolicy="no-referrer">'
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
        f'<img class="ticon" src="{esc(tree["icon"])}" alt="" referrerpolicy="no-referrer">'
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
        return "", '<h2>Talents</h2><p class="empty">Pas encore de points de talent.</p>'

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
    section = (
        '<details class="fold big" data-keep open><summary><span>Talents</span>'
        f'<span class="n">{esc(summary(groups[0]))}</span></summary><div class="fold-body">'
        + "".join(blocks) + "</div></details>"
    )
    return summary(groups[0]), section


def roles_html(c: Character) -> str:
    return ", ".join(
        f"{esc(LABELS[r])} ⭐" if r == c.preferred_role else esc(LABELS[r]) for r in roles_for(c.wow_class)
    )


def professions_html(c: Character) -> str:
    if not c.professions:
        return '<span class="muted">—</span>'
    ordered = sorted(c.professions.items(), key=lambda kv: (not is_primary(kv[0]), kv[0]))
    return "".join(
        f'<span class="tag">{esc(profession_label(p))}' + (f" <b>{skill}</b>" if skill is not None else "") + "</span>"
        for p, skill in ordered
    )


def recipe_card(recipe: GuildRecipe, crafted_by: dict, crafter_links: dict[str, int] | None) -> str:
    if recipe.reagents is None:
        reagents = '<li class="muted">composants inconnus pour l\'instant</li>'
    elif not recipe.reagents:
        reagents = '<li class="muted">aucun composant</li>'
    else:
        reagents = "".join(
            f'<li class="d{depth}">{qty}× {esc(name)}</li>'
            for depth, qty, name in expand_reagents(recipe.reagents, crafted_by, seen=frozenset({recipe.id}))
        )
    lines = []
    if recipe.description:
        lines.append(("effect", recipe.description))
    item = recipe.item or {}
    lines.extend((kind, text) for kind, text in item.get("lines", []))
    tip = "".join(f'<div class="{esc(kind)}">{esc(text)}</div>' for kind, text in lines)
    tip = f'<div class="tip">{tip}</div>' if tip else ""
    color = QUALITY_COLORS.get(item.get("quality") or "")
    title_style = f' style="color:{color}"' if color else ""
    who = ""
    if crafter_links is not None:
        links = ", ".join(
            f'<a href="/perso/{crafter_links[n]}">{esc(n)}</a>' if n in crafter_links else esc(n)
            for n in recipe.crafters
        )
        who = f'<div class="who">👥 {links}</div>'
    search = normalize(" ".join([recipe.name, *(r[1] for r in recipe.reagents or []), *(t for _, t in lines)]))
    return (
        f'<div class="card" data-search="{esc(search)}"><h4{title_style}>{esc(recipe.name)}</h4>'
        f"{tip}<ul>{reagents}</ul>{who}</div>"
    )


def recipes_by_family_html(recipes: list[GuildRecipe], crafted_by: dict, crafter_links: dict[str, int] | None) -> str:
    sections = []
    for family, members in group_by_family(filter_recipes(recipes, None)):
        cards = "".join(recipe_card(r, crafted_by, crafter_links) for r in members)
        sections.append(
            f'<details class="fold" data-section><summary><span>{esc(family)}</span>'
            f'<span class="n">{len(members)}</span></summary><div class="fold-body"><div class="cards">{cards}</div>'
            "</div></details>"
        )
    return "".join(sections)


class WebSite:
    def __init__(self, db: Database, guild_id: Callable[[], int | None]):
        self.db = db
        self._guild_id = guild_id
        self._runner: web.AppRunner | None = None

    # ------------------------------------------------------------ données

    def guild_id(self) -> int | None:
        """Le serveur Discord affiché : GUILD_ID, ou le seul serveur connu."""
        configured = self._guild_id()
        if configured:
            return configured
        known = self.db.known_guild_ids()
        return known[0] if len(known) == 1 else None

    def _scope(self) -> int:
        gid = self.guild_id()
        if gid is None:
            raise web.HTTPServiceUnavailable(text="Serveur Discord non déterminé : renseigne GUILD_ID dans le .env.")
        return gid

    # ------------------------------------------------------------ pages

    async def characters(self, request: web.Request) -> web.Response:
        gid = self._scope()
        characters = sorted(self.db.guild_characters(gid), key=lambda c: normalize(c.name))
        rows = []
        for c in characters:
            search = normalize(" ".join([c.name, class_label(c.wow_class), race_label(c.race)]))
            rows.append(
                f'<tr data-search="{esc(search)}" data-classe="{esc(c.wow_class)}" '
                f'data-role="{" ".join(roles_for(c.wow_class))}" data-metier="{" ".join(c.professions)}">'
                f'<td><a class="who-cell" href="/perso/{c.id}">{avatar_html(c)}<b>{esc(c.name)}</b></a></td>'
                f'<td class="num">{c.level or ""}</td>'
                f"<td>{class_span(c)}</td><td>{esc(race_label(c.race))}</td>"
                f"<td>{roles_html(c)}</td><td>{professions_html(c)}</td></tr>"
            )
        options = lambda items: "".join(f'<option value="{esc(k)}">{esc(v)}</option>' for k, v in items)  # noqa: E731
        body = f"""
<h1 class="title">Persos</h1>
<p class="sub"><span id="count">{len(characters)}</span> perso(s) · ⭐ rôle préféré</p>
<div class="filters">
  <input id="q" type="search" placeholder="Chercher un perso, une classe, une race…" autocomplete="off">
  <select data-filter="classe"><option value="">Toutes les classes</option>{options((k, v[0]) for k, v in CLASSES.items())}</select>
  <select data-filter="role"><option value="">Tous les rôles</option>{options((r, LABELS[r]) for r in ROLES)}</select>
  <select data-filter="metier"><option value="">Tous les métiers</option>{options((k, v[0]) for k, v in PROFESSIONS.items())}</select>
</div>
<div class="table-wrap"><table>
<thead><tr><th>Perso</th><th class="num">Niv.</th><th>Classe</th><th>Race</th><th>Rôles</th><th>Métiers</th></tr></thead>
<tbody>{"".join(rows) or '<tr><td colspan="6" class="empty">Aucun perso déclaré.</td></tr>'}</tbody>
</table></div>"""
        return page("Persos", "persos", body, FILTER_SCRIPT)

    async def character(self, request: web.Request) -> web.Response:
        gid = self._scope()
        try:
            character_id = int(request.match_info["id"])
        except ValueError:
            raise web.HTTPNotFound(text="Perso introuvable.")
        character = next((c for c in self.db.guild_characters(gid) if c.id == character_id), None)
        if character is None:
            raise web.HTTPNotFound(text="Perso introuvable.")

        prof_rows = "".join(
            f'<tr><td><a href="/metier/{esc(p)}">{esc(profession_label(p))}</a></td>'
            f'<td class="num">{skill if skill is not None else "?"}</td></tr>'
            for p, skill in sorted(character.professions.items(), key=lambda kv: (not is_primary(kv[0]), kv[0]))
        )
        synced = ""
        if character.armory_synced_at:
            when = datetime.fromtimestamp(character.armory_synced_at).strftime("%d/%m/%Y")
            synced = f" · synchronisé avec l'armurerie le {when}"

        known = self.db.character_recipe_ids(character.id)
        all_recipes = self.db.guild_recipes(gid)
        crafted_by = crafted_by_map(all_recipes)
        recipes_html = ""
        for profession in sorted({p for p in PROFESSIONS}, key=lambda p: (not is_primary(p), p)):
            mine = [r for r in self.db.guild_recipes(gid, profession) if r.id in known]
            if mine:
                recipes_html += (
                    f'<details class="fold big" data-section open><summary><span>{esc(profession_label(profession))}'
                    f'</span><span class="n">{len(mine)}</span></summary><div class="fold-body">'
                    + recipes_by_family_html(mine, crafted_by, None)
                    + "</div></details>"
                )
        if recipes_html:
            recipes_html = (
                '<div class="filters"><input id="q" type="search" '
                f'placeholder="Chercher une recette, un composant, un effet (ex. agilité)…" autocomplete="off">{FOLD_BUTTONS}</div>'
                + recipes_html
            )
        else:
            recipes_html = '<p class="empty">Pas de recettes connues (perso absent de l\'armurerie, ou sans métier).</p>'

        level = f"Niveau {character.level} · " if character.level else ""
        spec, talents_block = talents_html(character, self.db.talent_trees(character.wow_class))
        spec = f" · {esc(spec)}" if spec else ""
        render = ""
        if character.render_url and character.render_url.startswith("https://"):
            render = (
                f'<div class="render"><div class="frame"><img src="{esc(character.render_url)}" '
                f'alt="{esc(character.name)}" referrerpolicy="no-referrer"></div></div>'
            )
        professions_block = (
            f'<div class="table-wrap" style="max-width:420px"><table><thead><tr><th>Métier</th>'
            f'<th class="num">Niveau</th></tr></thead><tbody>{prof_rows}</tbody></table></div>'
            if prof_rows else '<p class="empty">Aucun métier déclaré.</p>'
        )
        body = f"""
<div class="hero"><div class="info">
<h1 class="title" style="color:{CLASS_COLORS.get(character.wow_class, "inherit")}">{esc(character.name)}</h1>
<p class="sub">{level}{esc(class_label(character.wow_class))} {esc(race_label(character.race))}{spec} · {roles_html(character)}{synced}</p>
<h2>Métiers</h2>
{professions_block}
</div>{render}</div>
{talents_block}
{recipes_html}"""
        return page(character.name, "persos", body, FILTER_SCRIPT)

    async def professions(self, request: web.Request) -> web.Response:
        gid = self._scope()
        tiles = []
        for key, (label, primary) in PROFESSIONS.items():
            count = len(self.db.characters_with_profession(gid, key))
            recipes = len(self.db.guild_recipes(gid, key))
            kind = "" if primary else " (secondaire)"
            tiles.append(
                f'<a class="tile" href="/metier/{key}"><div class="big">{esc(label)}</div>'
                f'<div class="muted">{count} perso(s){kind} · {recipes} recette(s)</div></a>'
            )
        body = f'<h1 class="title">Métiers</h1><p class="sub">Qui a quel métier, et les recettes connues sur le serveur.</p><div class="grid">{"".join(tiles)}</div>'
        return page("Métiers", "metiers", body)

    async def profession(self, request: web.Request) -> web.Response:
        gid = self._scope()
        key = request.match_info["key"]
        if key not in PROFESSIONS:
            raise web.HTTPNotFound(text="Métier inconnu.")
        label = profession_label(key)

        holders = self.db.characters_with_profession(gid, key)
        who_rows = "".join(
            f'<tr><td><a class="who-cell" href="/perso/{c.id}">{avatar_html(c)}<b>{esc(c.name)}</b></a></td>'
            f'<td>{class_span(c)}</td>'
            f'<td class="num">{skill if skill is not None else "?"}</td></tr>'
            for c, skill in holders
        )
        who = (
            f'<div class="table-wrap" style="max-width:560px"><table><thead><tr><th>Perso</th><th>Classe</th>'
            f'<th class="num">Niveau</th></tr></thead><tbody>{who_rows}</tbody></table></div>'
            if holders else '<p class="empty">Personne n\'a déclaré ce métier.</p>'
        )

        recipes = self.db.guild_recipes(gid, key)
        crafted_by = crafted_by_map(self.db.guild_recipes(gid))
        links = {c.name: c.id for c in self.db.guild_characters(gid)}
        recipes_html = (
            '<div class="filters"><input id="q" type="search" placeholder="Chercher une recette, un composant, un effet (ex. agilité)…" '
            f'autocomplete="off">{FOLD_BUTTONS}</div><p class="sub"><span id="count">{len(recipes)}</span> recette(s)</p>'
            + recipes_by_family_html(recipes, crafted_by, links)
            if recipes else '<p class="empty">Aucune recette connue (seuls les persos trouvés dans l\'armurerie en ont).</p>'
        )
        body = f"<h1 class=\"title\">{esc(label)}</h1><h2>Qui l'a</h2>{who}<h2>Recettes</h2>{recipes_html}"
        return page(label, "metiers", body, FILTER_SCRIPT)

    # ------------------------------------------------------------ serveur

    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/", self.characters)
        app.router.add_get("/perso/{id}", self.character)
        app.router.add_get("/metiers", self.professions)
        app.router.add_get("/metier/{key}", self.profession)
        return app

    async def start(self, host: str, port: int) -> None:
        self._runner = web.AppRunner(self.app(), access_log=None)
        await self._runner.setup()
        await web.TCPSite(self._runner, host, port).start()
        log.info("Site web démarré sur %s:%d", host, port)

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
