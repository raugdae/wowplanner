"""Petit site web public, en lecture seule : persos, métiers et recettes du serveur.

Aucune info personnelle : ni pseudo Discord, ni identifiant Discord, ni BattleTag, et rien qui
permette de relier deux persos au même joueur. Seuls les persos (nom, classe, race, rôles),
leurs métiers et leurs recettes sont affichés.

Servi par aiohttp dans le même processus que le bot (même base SQLite, lue seulement). Activé
par WEB_PORT ; derrière Traefik en production (voir docker-compose.traefik.yml).
"""
from __future__ import annotations

import html
import json
import logging
from datetime import datetime
from typing import Callable

from aiohttp import web

from .db import Character, Database, GuildRecipe
from .gamedata import (
    CLASSES, MAX_PROFESSION_SKILL, PROFESSIONS, class_label, is_primary, profession_label, race_label, roles_for,
)
from .recipes import crafted_by_map, expand_reagents, filter_recipes, group_by_category, normalize
from . import dungeon_guides, dungeons, gear, statsource
from .armory import icon_url
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
/* Métiers de la fiche perso : une colonne par métier. */
.prof-wrap { display:inline-block; max-width:100%; }
.prof-table th, .prof-table td { text-align:center; min-width:92px; padding:8px 12px; }
.prof-table th { white-space:nowrap; }
.prof-table td b { font-size:20px; color:var(--accent); }
.prof-table .split { border-left:3px double var(--line); }
.bar { height:5px; margin-top:5px; background:var(--panel2); border-radius:3px; overflow:hidden; }
.bar span { display:block; height:100%; background:var(--accent); border-radius:3px; }
/* Liste des persos : 2 colonnes de métiers principaux, puis une colonne fixe par métier secondaire (alignées). */
td.prof { min-width:112px; white-space:nowrap; line-height:1.15; }
td.prof small { display:block; font-size:11px; color:var(--muted); }
td.prof b, td.sec b { color:var(--accent); }
th.sec, td.sec { text-align:center; min-width:70px; }
.split { border-left:2px solid var(--line); }
td .none { color:var(--muted); opacity:.5; }
/* Onglets (recettes par métier). */
.tabs { display:flex; flex-wrap:wrap; gap:6px; margin:10px 0 4px; border-bottom:1px solid var(--line); }
.tabs button { background:var(--panel); color:var(--text); border:1px solid var(--line); border-bottom:none;
  border-radius:8px 8px 0 0; padding:8px 14px; font:inherit; cursor:pointer; margin-bottom:-1px; }
.tabs button .n { color:var(--muted); font-size:12px; margin-left:6px; }
.tabs button.active { background:var(--panel2); color:var(--accent); border-color:var(--accent); font-weight:700; }
.tabs button:disabled { opacity:.45; cursor:default; }
/* Armurerie : équipement façon fiche du jeu + caractéristiques. */
.armory { display:grid; grid-template-columns:minmax(0, 1fr) 300px; gap:18px; align-items:start; margin:10px 0 6px; }
.armory .main { min-width:0; }
.armory .main .talents { margin:14px 0 0; }
.doll { display:grid; grid-template-columns:minmax(0, 1fr) minmax(170px, 250px) minmax(0, 1fr);
  grid-template-areas:"left center right" "weapons weapons weapons"; gap:8px 12px; background:var(--panel);
  border:1px solid var(--line); border-radius:12px; padding:12px; }
.doll .left { grid-area:left; } .doll .right { grid-area:right; } .doll .center { grid-area:center; align-self:center; }
.doll .weapons { grid-area:weapons; display:flex; justify-content:center; gap:12px; flex-wrap:wrap; }
.doll .center .frame { width:100%; aspect-ratio:1 / 1.25; overflow:hidden; position:relative; }
.doll .center .frame::before { content:""; position:absolute; inset:10% 0 0; border-radius:50%;
  background:radial-gradient(closest-side, var(--glow), transparent); }
.doll .center img { position:relative; display:block; width:320%; max-width:none; margin:-72% 0 0 -110%;
  filter:drop-shadow(0 8px 18px rgba(0,0,0,.6)); }
.slots { display:flex; flex-direction:column; gap:6px; min-width:0; }
.slot { position:relative; display:flex; align-items:center; gap:8px; min-width:0; cursor:help; border-radius:8px; }
.left .slot { flex-direction:row-reverse; text-align:right; }
.weapons .slot { width:200px; }
.slot img, .slot .ph { flex:none; width:38px; height:38px; border-radius:6px; border:2px solid #4a4a4a;
  background:var(--panel2); display:block; }
.slot .txt { min-width:0; line-height:1.2; }
.slot .nm { font-size:13px; font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.slot .sb { font-size:11px; color:var(--muted); }
.slot.empty { cursor:default; opacity:.55; }
.slot.prio img { box-shadow:0 0 0 2px var(--accent); }
.slot:focus { outline:2px solid var(--accent); outline-offset:2px; }
.slot .tt, .tal .tt { display:none; position:absolute; top:calc(100% + 6px); left:0; width:270px; z-index:30;
  background:rgba(10,13,22,.97); color:#eee; border:1px solid #6a5a32; border-radius:8px; padding:8px 10px;
  font-size:13px; line-height:1.4; box-shadow:0 6px 22px rgba(0,0,0,.65); cursor:auto; text-align:left;
  font-weight:400; white-space:normal; }
.left .slot .tt { left:auto; right:0; }
.slot:hover .tt, .slot:focus .tt { display:block; }
.tt .type, .tt .bind, .tt .req, .tt .ilvl { color:#9a9a9a; }
.tt .stat.prio { color:#fff; font-weight:700; }
.tt .stat.prio::after { content:" ★"; color:#f2c75c; }
.tt .effect { color:#3ee05a; } .tt .enchant { color:#3ee05a; } .tt .set { color:#f2c75c; }
.tt .flavor { color:#e6c35c; font-style:italic; }
.statbox { background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:12px 14px; }
.statbox h3 { margin:0 0 8px; font-size:16px; }
.statbox h4 { margin:12px 0 4px; font-size:12px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); }
.srow { display:flex; align-items:center; gap:8px; padding:3px 6px; border-radius:6px; font-size:14px; }
.srow span { flex:1; } .srow b { font-variant-numeric:tabular-nums; }
.srow i { font-style:normal; font-size:11px; font-weight:700; min-width:18px; height:18px; line-height:18px;
  text-align:center; border-radius:9px; background:var(--panel2); color:var(--muted); }
.srow.p1, .srow.p2, .srow.p3 { background:linear-gradient(90deg, rgba(242,199,92,.22), transparent); }
.srow.p1 i, .srow.p2 i, .srow.p3 i { background:#f2c75c; color:#1a1406; }
.srow.p1 span, .srow.p2 span, .srow.p3 span { font-weight:700; }
.srow.capped b::after { content:" ✓"; color:#3ee05a; }
.prio-box select { font:inherit; font-weight:700; background:var(--panel); color:var(--accent);
  border:1px solid var(--line); border-radius:6px; padding:1px 4px; }
.prio-box { background:var(--panel2); border:1px solid var(--line); border-radius:10px; padding:8px 10px; font-size:13px; }
.prio-box .chips:not([hidden]) { display:flex; flex-wrap:wrap; gap:4px; margin-top:6px; }
.chip { border:1px solid var(--line); border-radius:999px; padding:1px 8px; font-size:12px; color:var(--muted); }
.chip.top { border-color:#f2c75c; color:#f2c75c; font-weight:700; }
.chip.done { text-decoration:line-through; opacity:.6; }
.statbox .src { font-size:11px; color:var(--muted); margin:10px 0 0; }
@media (max-width:900px) { .armory { grid-template-columns:minmax(0, 1fr); } }
@media (max-width:640px) {
  .doll { grid-template-columns:minmax(0, 1fr) minmax(0, 1fr); grid-template-areas:"center center" "left right" "weapons weapons";
    padding:10px; gap:8px; }
  .slot img, .slot .ph { width:34px; height:34px; }
  .doll .center { width:min(240px, 100%); margin:0 auto; }
  .left .slot { flex-direction:row; text-align:left; } .left .slot .tt { left:0; right:auto; }
  .right .slot .tt { left:auto; right:0; }
  .weapons .slot { width:100%; }
}
/* Arbres de talents façon jeu : grille 4 colonnes, infobulle au survol (ou au toucher sur mobile). */
.talents { margin:14px 0 6px; }
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
.tal .tt { top:calc(100% + 9px); left:-4px; width:260px; }
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
@media (max-width:640px) { .trees { justify-content:center; } }
@media (max-width:420px) { .tgrid { --ts:38px; gap:8px; } .tal .tt { width:220px; } }
/* Donjons */
.lvl-pick { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
.filters .lvl-pick input[type=number] { width:96px; flex:none; }
.lvl-pick label { display:flex; gap:6px; align-items:center; color:var(--muted); cursor:pointer; white-space:nowrap; }
.filters .lvl-pick input[type=checkbox] { flex:none; width:16px; height:16px; padding:0; margin:0; accent-color:var(--accent); }
.dname .zm { display:none; font-size:12px; color:var(--muted); }
@media (max-width:600px) {
  .dtable .zc, .dtable .pc { display:none; }
  .dname .zm { display:block; }
  .dtable td.lv { min-width:96px; }
}
.dname b { display:block; }
.dname .en { font-size:12px; color:var(--muted); }
.badge-new { display:inline-block; margin-left:6px; font-size:11px; font-weight:700; color:var(--bg);
  background:var(--accent); border-radius:999px; padding:0 7px; vertical-align:2px; }
.side { font-size:12px; color:var(--muted); }
.side.alliance::before { content:"🛡️ "; } .side.horde::before { content:"🪓 "; }
td.lv { white-space:nowrap; min-width:150px; }
td.lv b { font-variant-numeric:tabular-nums; }
.lbar { position:relative; height:6px; margin-top:6px; border-radius:3px; background:var(--panel2); }
.lbar span { position:absolute; top:0; bottom:0; border-radius:3px; background:var(--muted); opacity:.7; }
.lbar i { position:absolute; top:-3px; bottom:-3px; width:2px; background:var(--text); display:none;
  left:var(--lvpos, 0); }
.has-level .lbar i { display:block; }
tr.d-in td { background:color-mix(in srgb, var(--accent) 10%, transparent); }
tr.d-in .lbar span { background:var(--accent); opacity:1; }
tr.d-in td:first-child { box-shadow:inset 3px 0 0 var(--accent); }
tr.d-near .lbar span { background:var(--accent); opacity:.45; }
tr.d-near .lv b::after { content:" · bientôt"; color:var(--muted); font-weight:400; font-size:12px; }
tr.d-out { opacity:.55; }
.only-in tr.d-out { display:none; }
.who-avatars { display:flex; flex-wrap:wrap; gap:4px; align-items:center; }
.who-avatars .avatar { width:28px; height:28px; }
.who-avatars a:hover { text-decoration:none; }
.who-avatars a:hover .avatar { border-color:var(--accent); }
.who-avatars .more { color:var(--muted); font-size:12px; }
.status-open { color:#5fd38d; font-weight:600; }
p.src { color:var(--muted); font-size:12px; margin-top:10px; }
tr[data-href] { cursor:pointer; }
.dname a { color:inherit; }
.crumb { margin:0 0 10px; color:var(--muted); }
.dhero { display:flex; gap:18px; align-items:center; margin-bottom:18px; }
.dtile { width:180px; height:96px; object-fit:cover; border-radius:10px; border:1px solid var(--line); flex:none;
  box-shadow:0 4px 16px rgba(0,0,0,.4); }
.dtile.none { display:flex; align-items:center; justify-content:center; font-size:40px; background:var(--panel2); }
.dhero h1 .badge-new { font-family:system-ui,sans-serif; font-size:12px; vertical-align:6px; }
.dhero .sub { margin-bottom:8px; }
.facts { display:flex; gap:8px; flex-wrap:wrap; }
.fact { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:4px 12px; text-align:center; }
.fact small { display:block; color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.05em; }
.fact b { color:var(--accent); font-variant-numeric:tabular-nums; }
.dgrid { display:grid; grid-template-columns:minmax(0,3fr) minmax(0,2fr); gap:14px; }
.card { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:4px 16px 16px; }
.card h2 { margin:14px 0 8px; font-size:16px; }
.coords { display:flex; align-items:center; gap:10px; flex-wrap:wrap; background:var(--panel2); border:1px solid var(--line);
  border-radius:8px; padding:8px 10px; margin:10px 0; }
.coords .pin { font-size:20px; }
.coords > div { flex:1 1 140px; }
.copy { display:flex; align-items:center; gap:8px; background:var(--bg); color:var(--text); border:1px solid var(--line);
  border-radius:6px; padding:5px 8px; cursor:pointer; font:inherit; font-size:13px; max-width:100%; }
.copy code { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.copy span { color:var(--accent); font-weight:600; flex:none; }
.copy:hover { border-color:var(--accent); }
.btn { display:inline-block; margin-top:6px; padding:7px 12px; border-radius:8px; border:1px solid var(--accent);
  color:var(--accent); font-weight:600; }
.btn:hover { background:var(--accent); color:var(--bg); text-decoration:none; }
.who-list { display:flex; flex-direction:column; gap:8px; }
.who-list small { display:block; }
.route { list-style:none; margin:8px 0 0; padding:0; position:relative; max-width:760px; }
.route::before { content:""; position:absolute; left:17px; top:18px; bottom:18px; width:3px; border-radius:2px;
  background:linear-gradient(var(--accent), color-mix(in srgb, var(--accent) 30%, transparent)); }
.step { position:relative; display:flex; gap:14px; align-items:flex-start; padding:6px 0; }
.step .dot { position:relative; z-index:1; width:37px; height:37px; flex:none; border-radius:50%; display:flex;
  align-items:center; justify-content:center; font-weight:800; color:var(--bg); background:var(--accent);
  box-shadow:0 0 0 4px var(--bg), 0 0 14px color-mix(in srgb, var(--accent) 45%, transparent); }
.step.start .dot { background:var(--panel2); color:var(--text); border:2px solid var(--accent); font-size:16px; }
.step.opt .dot { background:var(--bg); color:var(--accent); border:2px dashed var(--accent); box-shadow:0 0 0 4px var(--bg); }
.step .sbody { flex:1; background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:7px 12px; }
.step.start .sbody { background:transparent; border:none; padding-top:8px; }
.step.opt .sbody { border-style:dashed; opacity:.85; }
.step .en { display:block; color:var(--muted); font-size:12px; }
.step .where { color:var(--muted); font-size:13px; margin-top:2px; }
.otag { margin-left:8px; font-size:11px; color:var(--muted); border:1px solid var(--line); border-radius:999px; padding:0 7px; }
.dnav { display:flex; justify-content:space-between; gap:10px; margin-top:24px; padding-top:12px; border-top:1px solid var(--line); }
.dnav a { color:var(--accent); }
@media (max-width:700px) {
  .dgrid { grid-template-columns:1fr; }
  .dhero { flex-direction:column; align-items:flex-start; }
  .dtile { width:100%; height:120px; }
  .dtile.none { display:none; }
}
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
    document.querySelectorAll(".tabs button[data-tab]").forEach(b => {
      const panel = document.querySelector(`[data-panel="${b.dataset.tab}"]`);
      const n = panel ? panel.querySelectorAll("[data-search]:not([hidden])").length : 0;
      const badge = b.querySelector(".n");
      if (badge) badge.textContent = n;
      b.disabled = !!text && !n;
    });
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

TABS_SCRIPT = """
<script>
(() => {
  const buttons = [...document.querySelectorAll(".tabs button[data-tab]")];
  const panels = [...document.querySelectorAll("[data-panel]")];
  function show(key) {
    buttons.forEach(b => b.classList.toggle("active", b.dataset.tab === key));
    panels.forEach(p => p.hidden = p.dataset.panel !== key);
    try { localStorage.setItem("wowplanner-tab", key); } catch (e) {}
  }
  buttons.forEach(b => b.addEventListener("click", () => show(b.dataset.tab)));
  let saved = null;
  try { saved = localStorage.getItem("wowplanner-tab"); } catch (e) {}
  if (buttons.length) show(buttons.some(b => b.dataset.tab === saved) ? saved : buttons[0].dataset.tab);
})();
</script>
"""

# Choix d'une autre spé dans le panneau de caractéristiques : rangs, cap de toucher et stats phares des objets.
SPEC_SCRIPT = """
<script>
(() => {
  const select = document.getElementById("spec");
  const raw = document.getElementById("spec-data");
  if (!select || !raw) return;
  const views = JSON.parse(raw.textContent);
  select.addEventListener("change", () => {
    const v = views[select.value];
    document.querySelectorAll(".prio-box .chips").forEach(c => c.hidden = c.dataset.spec !== select.value);
    document.querySelectorAll(".srow[data-k]").forEach(row => {
      const k = row.dataset.k, rank = v.ranks[k], capped = k === v.capped;
      row.classList.remove("p1", "p2", "p3", "capped");
      if (rank && rank <= 3 && !capped) row.classList.add("p" + rank);
      if (capped) row.classList.add("capped");
      row.querySelector("i").textContent = rank || "";
    });
    const top = t => (t || "").split(" ").some(x => v.top.includes(x));
    document.querySelectorAll(".slot[data-t]").forEach(el => el.classList.toggle("prio", top(el.dataset.t)));
    document.querySelectorAll(".tt .stat[data-t]").forEach(el => el.classList.toggle("prio", top(el.dataset.t)));
  });
})();
</script>
"""

# Page Donjons : on choisit un niveau (ou un perso) et on voit les donjons de sa tranche.
DUNGEON_SCRIPT = """
<script>
(() => {
  const input = document.getElementById("lvl"), who = document.getElementById("lvl-who");
  const only = document.getElementById("lvl-only"), table = document.getElementById("dungeons");
  if (!input || !table) return;
  const rows = [...table.querySelectorAll("tr[data-low]")];
  const min = +table.dataset.min, max = +table.dataset.max;
  function apply() {
    const lv = parseInt(input.value, 10), ok = lv >= 1 && lv <= 60;
    table.classList.toggle("has-level", ok);
    table.classList.toggle("only-in", ok && only.checked);
    table.style.setProperty("--lvpos", ok ? (Math.min(Math.max(lv, min), max) - min) / (max - min) * 100 + "%" : "0");
    for (const r of rows) {
      const low = +r.dataset.low, high = +r.dataset.high;
      const state = !ok ? "" : lv >= low && lv <= high ? "in" : lv < low && low - lv <= 2 ? "near" : "out";
      r.classList.remove("d-in", "d-near", "d-out");
      if (state) r.classList.add("d-" + state);
    }
    try { localStorage.setItem("wp-dungeon-level", ok ? String(lv) : ""); } catch (e) {}
  }
  who.addEventListener("change", () => { if (who.value) input.value = who.value; apply(); });
  input.addEventListener("input", () => { who.value = ""; apply(); });
  only.addEventListener("change", apply);
  try { const saved = localStorage.getItem("wp-dungeon-level"); if (saved && !input.value) input.value = saved; } catch (e) {}
  apply();
})();
</script>
"""

# Lignes de tableau cliquables (data-href), sans gêner les liens qu'elles contiennent.
ROW_LINK_SCRIPT = """
<script>
document.querySelectorAll("tr[data-href]").forEach(tr => tr.addEventListener("click", e => {
  if (!e.target.closest("a, button, input, select") && !getSelection().toString()) location.href = tr.dataset.href;
}));
</script>
"""

# Bouton « Copier » de la commande /way.
COPY_SCRIPT = """
<script>
document.querySelectorAll("button[data-copy]").forEach(b => b.addEventListener("click", async () => {
  const label = b.querySelector("span");
  try { await navigator.clipboard.writeText(b.dataset.copy); label.textContent = "Copié !"; }
  catch (e) { label.textContent = "Sélectionne et copie"; }
  setTimeout(() => label.textContent = "Copier", 1800);
}));
</script>
"""

FOLD_BUTTONS = (
    '<button type="button" data-fold="open">Tout déplier</button>'
    '<button type="button" data-fold="close">Tout replier</button>'
)


def page(title: str, active: str, body: str, scripts: str = "") -> web.Response:
    nav = "".join(
        f'<a href="{href}" class="{"active" if key == active else ""}">{label}</a>'
        for key, href, label in (("persos", "/", "Persos"), ("metiers", "/metiers", "Métiers"), ("donjons", "/donjons", "Donjons"))
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
            cells.append(
                f'<div class="srow{css}" data-k="{key}"><i>{rank or ""}</i><span>{esc(label)}</span>'
                f"<b>{esc(shown)}</b></div>"
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
    return f'<aside class="statbox"><h3>Caractéristiques</h3>{prio}{"".join(groups)}{source}{data}</aside>'


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
    for family, members in group_by_category(filter_recipes(recipes, None)):
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
                f"<td>{roles_html(c)}</td>{professions_cells(c)}</tr>"
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
<thead><tr><th>Perso</th><th class="num">Niv.</th><th>Classe</th><th>Race</th><th>Rôles</th>
<th colspan="2">Métiers principaux</th>{"".join(
    f'<th class="sec{" split" if i == 0 else ""}">{esc(profession_label(p))}</th>' for i, p in enumerate(SECONDARY_PROFESSIONS)
)}</tr></thead>
<tbody>{"".join(rows) or f'<tr><td colspan="{7 + len(SECONDARY_PROFESSIONS)}" class="empty">Aucun perso déclaré.</td></tr>'}</tbody>
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

        synced = ""
        if character.armory_synced_at:
            when = datetime.fromtimestamp(character.armory_synced_at).strftime("%d/%m/%Y")
            synced = f" · synchronisé avec l'armurerie le {when}"

        known = self.db.character_recipe_ids(character.id)
        all_recipes = self.db.guild_recipes(gid)
        crafted_by = crafted_by_map(all_recipes)
        tabs, panels = [], []
        for profession in sorted({p for p in PROFESSIONS}, key=lambda p: (not is_primary(p), p)):
            mine = [r for r in self.db.guild_recipes(gid, profession) if r.id in known]
            if mine:
                tabs.append(
                    f'<button type="button" data-tab="{esc(profession)}">{esc(profession_label(profession))}'
                    f'<span class="n">{len(mine)}</span></button>'
                )
                panels.append(
                    f'<div data-panel="{esc(profession)}">' + recipes_by_family_html(mine, crafted_by, None) + "</div>"
                )
        recipes_html = ""
        if tabs:
            recipes_html = (
                '<h2>Recettes</h2><div class="filters"><input id="q" type="search" '
                f'placeholder="Chercher une recette, un composant, un effet (ex. agilité)…" autocomplete="off">{FOLD_BUTTONS}</div>'
                f'<div class="tabs" role="tablist">{"".join(tabs)}</div>' + "".join(panels)
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
        professions_block = professions_table(character)
        spec_key = gear.detect_spec(character.talents, character.preferred_role, character.equipment)
        guessed = spec_key is None
        spec_key = spec_key or gear.default_spec(character.wow_class, character.preferred_role)
        icons = self.db.item_icons({i.get("id") for i in character.equipment or []})
        # Les arbres de talents vont sous l'équipement, dans la même colonne (à côté des caractéristiques).
        armory = armory_html(character, spec_key, icons, talents_block, guessed)
        if armory:
            talents_block = ""
        title = f"""<h1 class="title" style="color:{CLASS_COLORS.get(character.wow_class, "inherit")}">{esc(character.name)}</h1>
<p class="sub">{level}{esc(class_label(character.wow_class))} {esc(race_label(character.race))}{spec} · {roles_html(character)}{synced}</p>"""
        # Ordre : perso (équipement, stats), talents, puis métiers et recettes.
        if armory:
            top = f"{title}{armory}"
        else:
            top = f'<div class="hero"><div class="info">{title}</div>{render}</div>'
        body = f"""
{top}
{talents_block}
<h2>Métiers</h2>
{professions_block}
{recipes_html}"""
        return page(character.name, "persos", body, FILTER_SCRIPT + TABS_SCRIPT + SPEC_SCRIPT)

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

    async def dungeons(self, request: web.Request) -> web.Response:
        gid = self._scope()
        characters = sorted(
            (c for c in self.db.guild_characters(gid) if c.level),
            key=lambda c: (-(c.level or 0), normalize(c.name)),
        )
        lo, hi = dungeons.LEVEL_MIN, dungeons.LEVEL_MAX
        span = hi - lo

        def players_in(low: int, high: int) -> str:
            inside = [c for c in characters if low <= (c.level or 0) <= high]
            if not inside:
                return '<span class="muted">—</span>'
            shown = "".join(
                f'<a href="/perso/{c.id}" title="{esc(c.name)} · niv. {c.level}">{avatar_html(c)}</a>' for c in inside[:8]
            )
            more = f'<span class="more">+{len(inside) - 8}</span>' if len(inside) > 8 else ""
            return f'<div class="who-avatars">{shown}{more}</div>'

        def name_cell(name: str, english: str, new: bool, zone: str, slug: str) -> str:
            badge = '<span class="badge-new">Nouveau</span>' if new else ""
            return (
                f'<td class="dname"><a href="/donjon/{slug}"><b>{esc(name)}{badge}</b></a>'
                f'<span class="en">{esc(english)}</span><span class="zm">📍 {esc(zone)}</span></td>'
            )

        rows = []
        for d in dungeons.DUNGEONS:
            start = max(d.low, lo)
            left = (start - lo) / span * 100
            width = max((d.high - start) / span * 100, 2)
            side = f'<div class="side {d.side}">Côté {d.side.capitalize()}</div>' if d.side else ""
            search = normalize(" ".join([d.name, d.english, d.zone]))
            rows.append(
                f'<tr data-search="{esc(search)}" data-low="{d.low}" data-high="{d.high}" data-href="/donjon/{d.slug}">'
                f'{name_cell(d.name, d.english, d.new, d.zone, d.slug)}<td class="zc">{esc(d.zone)}{side}</td>'
                f'<td class="lv"><b>{d.low}–{d.high}</b><div class="lbar">'
                f'<span style="left:{left:.1f}%;width:{width:.1f}%"></span><i></i></div></td>'
                f'<td class="num pc">{d.players}</td><td>{players_in(d.low, d.high)}</td></tr>'
            )
        raid_rows = []
        for r in dungeons.RAIDS:
            status = dungeons.raid_status(r)
            note = f'<div class="side">{esc(r.note)}</div>' if r.note else ""
            raid_rows.append(
                f'<tr data-href="/donjon/{r.slug}">{name_cell(r.name, r.english, r.new, r.zone, r.slug)}<td class="zc">{esc(r.zone)}{note}</td>'
                f'<td class="num">{r.players}</td><td class="num">{r.bosses or "?"}</td>'
                f'<td class="{"status-open" if status == "Ouvert" else "muted"}">{esc(status)}</td>'
                f"<td>{players_in(dungeons.RAID_LEVEL, dungeons.RAID_LEVEL)}</td></tr>"
            )
        options = "".join(f'<option value="{c.level}">{esc(c.name)} ({c.level})</option>' for c in characters)
        body = f"""
<h1 class="title">Donjons</h1>
<p class="sub">{len(dungeons.DUNGEONS)} donjons de WoW Forever, du plus bas au plus haut niveau, avec les persos du
serveur qui sont dans la tranche. Choisis un niveau pour voir ce qui est à faire, et clique sur un donjon pour
voir son entrée et ses boss.</p>
<div class="filters">
  <input id="q" type="search" placeholder="Chercher un donjon, une zone…" autocomplete="off">
  <div class="lvl-pick">
    <select id="lvl-who" aria-label="Perso"><option value="">Niveau d'un perso…</option>{options}</select>
    <input id="lvl" type="number" min="1" max="60" placeholder="Niveau" aria-label="Niveau">
    <label><input id="lvl-only" type="checkbox"> Seulement sa tranche</label>
  </div>
</div>
<div class="table-wrap"><table id="dungeons" class="dtable" data-min="{lo}" data-max="{hi}">
<thead><tr><th>Donjon</th><th class="zc">Zone</th><th>Niveaux</th><th class="num pc">Joueurs</th>
<th>Persos dans la tranche</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table></div>
<h2>Raids</h2>
<div class="table-wrap"><table class="dtable">
<thead><tr><th>Raid</th><th class="zc">Accès</th><th class="num">Joueurs</th><th class="num">Boss</th><th>Ouverture</th>
<th>Persos {dungeons.RAID_LEVEL}</th></tr></thead>
<tbody>{"".join(raid_rows)}</tbody></table></div>
<p class="src">Niveaux conseillés, pas des verrous d'entrée. D'après Blizzard et les récapitulatifs de PC Games et
Warcraft Tavern ({dungeons.SOURCES_CHECKED}) : l'API Blizzard ne fournit pas le journal des donjons de Forever.</p>"""
        return page("Donjons", "donjons", body, FILTER_SCRIPT + DUNGEON_SCRIPT + ROW_LINK_SCRIPT)

    async def dungeon(self, request: web.Request) -> web.Response:
        """Fiche d'un donjon ou d'un raid : entrée, coordonnées, parcours des boss, persos du bon niveau."""
        gid = self._scope()
        slug = request.match_info["slug"]
        everything = [*dungeons.DUNGEONS, *dungeons.RAIDS]
        found = next((x for x in everything if x.slug == slug), None)
        if found is None:
            raise web.HTTPNotFound(text="Donjon inconnu.")
        guide = dungeon_guides.GUIDES.get(slug) or dungeon_guides.Guide("")
        is_raid = isinstance(found, dungeons.Raid)
        low, high = (dungeons.RAID_LEVEL, dungeons.RAID_LEVEL) if is_raid else (found.low, found.high)

        facts = [f'<span class="fact"><small>Niveaux</small><b>{low}–{high}</b></span>' if not is_raid else
                 f'<span class="fact"><small>Niveau</small><b>{low}</b></span>',
                 f'<span class="fact"><small>Joueurs</small><b>{found.players}</b></span>',
                 f'<span class="fact"><small>Boss</small><b>{len(guide.bosses) or "?"}</b></span>']
        if is_raid:
            facts.append(f'<span class="fact"><small>Ouverture</small><b>{esc(dungeons.raid_status(found))}</b></span>')
        side = getattr(found, "side", None)
        sub = esc(found.zone) + (f' · <span class="side {side}">Côté {side.capitalize()}</span>' if side else "")
        badge = '<span class="badge-new">Nouveau</span>' if found.new else ""
        tile = (
            f'<img class="dtile" src="{esc(guide.tile_url)}" alt="" referrerpolicy="no-referrer">'
            if guide.tile_url else '<div class="dtile none">🏰</div>'
        )

        # Entrée
        entry = [f"<p>{esc(guide.how)}</p>" if guide.how else ""]
        way = guide.way()
        if way:
            x, y = guide.coords
            entry.append(
                f'<div class="coords"><span class="pin">📍</span><div><b>{esc(guide.map_name)}</b>'
                f'<span class="muted"> · {x:g}, {y:g}</span></div>'
                f'<button type="button" class="copy" data-copy="{esc(way)}" title="Copier pour TomTom">'
                f"<code>{esc(way)}</code><span>Copier</span></button></div>"
            )
        else:
            entry.append('<p class="muted">Coordonnées exactes pas encore relevées.</p>')

        # Parcours des boss, façon tracé de donjon : étapes numérotées, les optionnels en pointillé.
        steps, n = [], 0
        for boss in guide.bosses:
            if boss.optional:
                mark, cls = "◇", " opt"
            else:
                n += 1
                mark, cls = str(n), ""
            name = dungeon_guides.boss_name(boss)
            same = name.replace("’", "'").casefold() == boss.name.replace("’", "'").casefold()
            en = f'<span class="en">{esc(boss.name)}</span>' if not same else ""
            tag = '<span class="otag">optionnel</span>' if boss.optional else ""
            where = f'<div class="where">{esc(boss.where)}</div>' if boss.where else ""
            steps.append(
                f'<li class="step{cls}"><span class="dot">{mark}</span><div class="sbody">'
                f"<b>{esc(name)}</b>{tag}{en}{where}</div></li>"
            )
        route = (
            '<ol class="route"><li class="step start"><span class="dot">⛩</span><div class="sbody"><b>Entrée</b></div></li>'
            + "".join(steps) + "</ol>"
            if steps else '<p class="empty">Boss pas encore documentés.</p>'
        )
        notes = "".join(f'<p class="muted">ℹ️ {esc(t)}</p>' for t in guide.notes)

        inside = [
            c for c in sorted(self.db.guild_characters(gid), key=lambda c: (-(c.level or 0), normalize(c.name)))
            if c.level and low <= c.level <= high
        ]
        who = "".join(
            f'<a class="who-cell" href="/perso/{c.id}">{avatar_html(c)}<span><b>{esc(c.name)}</b>'
            f'<small class="muted"> {class_span(c)} · {c.level}</small></span></a>'
            for c in inside
        ) or '<p class="empty">Aucun perso du serveur dans la tranche.</p>'

        link = (
            f'<a class="btn" href="{esc(guide.guide_url)}" target="_blank" rel="noopener noreferrer">'
            "🗺️ Carte détaillée et stratégies (Warcraft Tavern) ↗</a>"
            if guide.guide_url else ""
        )
        index = everything.index(found)
        prev_ = everything[index - 1] if index > 0 else None
        next_ = everything[index + 1] if index + 1 < len(everything) else None
        nav = '<nav class="dnav">' + (
            f'<a href="/donjon/{prev_.slug}">← {esc(prev_.name)}</a>' if prev_ else "<span></span>"
        ) + (f'<a href="/donjon/{next_.slug}">{esc(next_.name)} →</a>' if next_ else "<span></span>") + "</nav>"

        body = f"""
<p class="crumb"><a href="/donjons">← Tous les donjons</a></p>
<div class="dhero">{tile}<div>
<h1 class="title">{esc(found.name)}{badge}</h1>
<p class="sub">{esc(found.english)} · {sub}</p>
<div class="facts">{"".join(facts)}</div></div></div>
<div class="dgrid">
<section class="card"><h2>Entrée</h2>{"".join(entry)}{link}</section>
<section class="card"><h2>Persos dans la tranche</h2><div class="who-list">{who}</div></section>
</div>
<h2>Parcours des boss</h2>
<p class="sub">Dans l'ordre habituel ; ◇ = optionnel (rare, invoqué ou pas nécessaire pour finir).</p>
{route}{notes}
<p class="src">Entrée et boss d'après les guides de Warcraft Tavern ({dungeons.SOURCES_CHECKED}) ; noms français du
Journal de Blizzard quand il les donne. Vignette : Blizzard. L'API Blizzard ne fournit ni carte ni coordonnées pour
Forever : la carte détaillée est sur le guide.</p>
{nav}"""
        return page(found.name, "donjons", body, COPY_SCRIPT)

    # ------------------------------------------------------------ serveur

    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/", self.characters)
        app.router.add_get("/perso/{id}", self.character)
        app.router.add_get("/metiers", self.professions)
        app.router.add_get("/metier/{key}", self.profession)
        app.router.add_get("/donjons", self.dungeons)
        app.router.add_get("/donjon/{slug}", self.dungeon)
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
