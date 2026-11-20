"""Mise en page commune du site : en-tête, menu du compte, thèmes, scripts partagés, petits utilitaires.

La feuille de style est dans static/site.css. Le visiteur de la requête en cours (_VIEWER) est posé par le
middleware de connexion de web.py.
"""
from __future__ import annotations

import html
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from aiohttp import web

from . import __version__
from .db import Character
from .gamedata import (
    class_label,
)
from .webauth import (
    safe_next,
)


@dataclass
class Viewer:
    """Visiteur de la requête en cours, quand la connexion Discord est activée."""
    user: dict[str, Any] | None  # {"id", "name", …} si connecté
    path: str  # page demandée (pour y revenir après connexion)
    characters: list[Character] = field(default_factory=list)  # ses persos (menu du compte)
    admin: bool = False  # permission « Gérer le serveur » sur Discord
    guest: bool = False  # accès invité (mot de passe, sans Discord) : lecture seule


# Posé par le middleware de connexion le temps d'une requête ; None = connexion désactivée (site ouvert).
_VIEWER: ContextVar[Viewer | None] = ContextVar("viewer", default=None)


def members_visible() -> bool:
    """Les persos du serveur peuvent-ils être montrés ? (connexion désactivée, ou visiteur connecté)"""
    viewer = _VIEWER.get()
    return viewer is None or viewer.user is not None


def login_url(path: str) -> str:
    return f"/auth/login?next={quote(safe_next(path), safe='')}"


def _menu_html() -> str:
    """Menu en haut à droite : compte, persos du joueur (préféré en tête), thème, administration, déconnexion."""
    viewer = _VIEWER.get()
    themes = "".join(f'<option value="{k}">{esc(v)}</option>' for k, v in THEMES.items())
    theme = (
        '<div class="menu-sec"><label class="menu-theme">Thème'
        f'<select id="theme" aria-label="Thème">{themes}</select></label></div>'
    )
    if viewer is None or not viewer.user:
        login = ""
        if viewer is not None:
            login = f'<a class="account login" href="{esc(login_url(viewer.path))}">Se connecter avec Discord</a>'
        return (
            f'<div class="account-zone">{login}<details class="usermenu"><summary aria-label="Menu">☰</summary>'
            f'<div class="menu-panel">{theme}</div></details></div>'
        )
    chars = sorted(viewer.characters, key=lambda c: (not c.favorite, c.name.lower()))
    links = "".join(
        f'<a class="menu-char" href="/perso/{c.id}">{avatar_html(c)}<span>{"⭐ " if c.favorite else ""}{esc(c.name)}'
        f'<small>{esc(class_label(c.wow_class))}{f" · {c.level}" if c.level else ""}</small></span></a>'
        for c in chars
    ) or '<p class="muted">Aucun perso déclaré.</p>'
    admin = '<a class="menu-link" href="/admin">🛠️ Administration</a>' if viewer.admin else ""
    name = esc(viewer.user.get("name", "?"))
    head = "Connecté en <b>invité</b> (lecture seule)" if viewer.guest else f"Connecté en tant que <b>{name}</b>"
    return f"""<div class="account-zone"><details class="usermenu"><summary>👤 {name} ▾</summary>
<div class="menu-panel"><div class="menu-head">{head}</div>
<div class="menu-sec"><small>Mes persos</small>{links}<a class="menu-link" href="/mes-persos">Gérer mes persos →</a>
<a class="menu-link" href="/rentabilite">💰 Rentabilité de mes métiers</a>
<a class="menu-link" href="/calculatrice">🧮 Calculatrice HdV</a></div>
{theme}{admin}<a class="menu-link" href="/auth/logout">Déconnexion</a></div></details></div>"""

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

# Équipement fabricable (fiche perso) : filtre « seulement les améliorations », section ouverte mémorisée.
GEAR_SCRIPT = """
<script>
(() => {
  const box = document.getElementById("gear-only-up"), groups = document.querySelector(".gear-groups");
  const fold = document.getElementById("equipement-fabricable");
  if (box && groups) box.addEventListener("change", () => groups.classList.toggle("only-up", box.checked));
  if (!fold) return;
  try { if (localStorage.getItem("wp-gear-open") === "1") fold.open = true; } catch (e) {}
  fold.addEventListener("toggle", () => { try { localStorage.setItem("wp-gear-open", fold.open ? "1" : ""); } catch (e) {} });
})();
</script>
"""

# Menu du compte : se ferme au clic ailleurs ou avec Échap.
MENU_SCRIPT = """
<script>
(() => {
  const menu = document.querySelector("details.usermenu");
  if (!menu) return;
  document.addEventListener("click", e => { if (menu.open && !menu.contains(e.target)) menu.open = false; });
  document.addEventListener("keydown", e => { if (e.key === "Escape") menu.open = false; });
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
    links = [("sorties", "/sorties", "Sorties"), ("persos", "/", "Guilde"), ("metiers", "/metiers", "Métiers"),
             ("atelier", "/atelier", "Atelier"), ("hdv", "/hdv", "Hôtel des ventes"),
             ("donjons", "/donjons", "Donjons")]
    nav = "".join(
        f'<a href="{href}" class="{"active" if key == active else ""}">{label}</a>' for key, href, label in links
    )
    document = f"""<!doctype html>
<html lang="fr" data-theme="{DEFAULT_THEME}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} · WoW Planner</title>{THEME_BOOT}<link rel="stylesheet" href="/static/site.css?v={__version__}"></head>
<body><header><a class="brand title" href="/">WoW Planner</a><nav>{nav}</nav>{_menu_html()}</header>
<main>{body}</main>
<footer>Données des persos déclarés sur le Discord, complétées par l'armurerie Blizzard (WoW Forever).</footer>
{THEME_SCRIPT}{MENU_SCRIPT}{scripts}</body></html>"""
    return web.Response(text=document, content_type="text/html")


def class_span(c: Character) -> str:
    return f'<span style="color:{CLASS_COLORS.get(c.wow_class, "inherit")}">{esc(class_label(c.wow_class))}</span>'


def avatar_html(c: Character) -> str:
    if c.avatar_url and c.avatar_url.startswith("https://"):
        return f'<img class="avatar" src="{esc(c.avatar_url)}" alt="" loading="lazy" referrerpolicy="no-referrer">'
    return '<span class="avatar none">👤</span>'


