"""Page « Rentabilité » : ce que rapportent les métiers d'un de ses persos, aux prix de l'hôtel des ventes.

Calculs dans profit.py ; prix et catalogue des objets dans la base locale (cogs/auctions.py).
"""
from __future__ import annotations

from datetime import datetime

from aiohttp import web

from .auctions import money_text
from .db import Character
from .gamedata import is_primary, profession_label
from .profit import (
    AH_CUT, GATHERING, VENDOR_REAGENTS, CraftPlan, CraftStep, craft_plan, gathered_value, gathering_rows, raw_unit,
    recipe_profits,
)
from .recipes import normalize
from .web import _VIEWER, esc
from .webauction import COIN_HEADS, LIST_SCRIPT, AuctionPages, item_icon, item_name, money_cells, number

# Au-delà, les recettes les moins rentables sont repliées.
SHOWN_RECIPES = 40
# Quantité maximale saisie par objet dans la calculatrice.
MAX_STOCK = 100_000
# Précisions sur certaines récoltes.
GATHERING_NOTES = {"peche": " (le niveau de pêche requis n'est pas connu par poisson)"}


def signed_money(copper: int | None) -> str:
    """Bénéfice signé et coloré (vert / rouge), en texte po/pa/pc."""
    if copper is None:
        return '<span class="muted">?</span>'
    if copper == 0:
        return '<span class="muted">0</span>'
    sign, cls = ("+", "gain") if copper > 0 else ("−", "loss")
    return f'<span class="{cls}">{sign} {esc(money_text(abs(copper)))}</span>'


SOURCE_LABELS = {"hdv": "HdV", "marchand": "marchand"}


class ProfitPages(AuctionPages):
    """Pages « Rentabilité de mes métiers » et « Calculatrice HdV », toujours pour un perso du joueur connecté."""

    def register_profit(self, router: web.UrlDispatcher) -> None:
        router.add_get("/rentabilite", self.profit_page)
        router.add_get("/calculatrice", self.calculator_page)

    def _pick_character(
        self, request: web.Request, title: str, active: str, action: str, why: str,
    ) -> tuple[web.Response | None, Character | None, str]:
        """(page d'erreur, perso choisi, menu de choix du perso). Le perso : celui demandé, sinon le préféré, sinon le
        premier qui a un métier."""
        if not self.house:
            return self._disabled(request), None, ""
        viewer = _VIEWER.get()
        if self._web_user() is None or viewer is None:
            body = f'<h1 class="title">{title}</h1><p class="muted">Connexion Discord nécessaire : {esc(why)}</p>'
            return self._render(request, title, active, body), None, ""
        crafters = [c for c in viewer.characters if c.professions]
        if not crafters:
            body = (
                f'<h1 class="title">{title}</h1><p class="empty">Aucun de tes persos n\'a de métier connu. Les métiers '
                'viennent de l\'armurerie : ajoute tes persos dans <a href="/mes-persos">Mes persos</a>.</p>'
            )
            return self._render(request, title, active, body), None, ""
        wanted = request.query.get("perso", "")
        character = next((c for c in crafters if str(c.id) == wanted), None)
        if character is None:
            character = next((c for c in crafters if c.favorite), crafters[0])
        options = "".join(
            f'<option value="{c.id}"{" selected" if c.id == character.id else ""}>{"⭐ " if c.favorite else ""}'
            f'{esc(c.name)} — {esc(", ".join(profession_label(p) for p in c.professions))}</option>'
            for c in crafters
        )
        picker = (
            f'<form method="get" action="{action}" class="filters"><select name="perso" data-autosubmit '
            f'aria-label="Perso">{options}</select><noscript><button class="act">Voir</button></noscript></form>'
        )
        return None, character, picker

    def _prices_when(self) -> str:
        snapshot = self.site.db.ah_snapshot_time()
        return f"{datetime.fromtimestamp(snapshot, self.tz):%H:%M le %d/%m}" if snapshot else "pas encore relevés"

    def _known_recipes(self, character: Character, profession: str | None = None) -> list:
        """Recettes connues du perso (d'un métier, ou de tous), avec leurs détails."""
        gid = self.site.guild_id()
        if gid is None:
            return []
        known = self.site.db.character_recipe_ids(character.id)
        return [r for r in self.site.db.guild_recipes(gid, profession) if r.id in known]

    async def profit_page(self, request: web.Request) -> web.Response:
        title = "Rentabilité de mes métiers"
        error, character, picker = self._pick_character(
            request, title, "rentabilite", "/rentabilite", "la page montre ce que rapportent les métiers de tes persos."
        )
        if error is not None:
            return error
        assert character is not None
        sections = []
        professions = sorted(character.professions.items(), key=lambda p: (not is_primary(p[0]), p[0]))
        for key, skill in professions:
            level = f" · niveau {skill}" if skill is not None else ""
            if key in GATHERING:
                sections.append(self._gathering_section(key, skill, level))
            recipes = self._known_recipes(character, key)
            if recipes:
                sections.append(self._crafting_section(key, recipes, level))
            elif key not in GATHERING:
                sections.append(
                    f'<section class="card admin-sec"><h2>{esc(profession_label(key))}{esc(level)}</h2>'
                    '<p class="empty">Aucune recette connue dans l\'armurerie pour ce perso.</p></section>'
                )
        body = f"""
<h1 class="title">{title}</h1>
<p class="sub">Ce que rapportent les métiers de ton perso aux prix de l'<a href="/hdv">hôtel des ventes</a>
(n° {self.house}, prix de {self._prices_when()}). Vente au prix le plus bas actuel, commission de {AH_CUT * 100:.0f} %
déduite ; composants au prix le plus bas de l'HdV, ou au prix du marchand pour ceux qu'il vend (fioles, fils, teintures,
flux, épices…). « Marchand » : ce que le marchand te donne pour l'objet. 🧮 <a href="/calculatrice?perso={character.id}">
Calculer avec ton stock</a>.</p>
{picker}
{"".join(sections)}"""
        return self._render(request, title, "rentabilite", body, LIST_SCRIPT + PROFIT_SCRIPT)

    # ------------------------------------------------------------ calculatrice

    def _stock_candidates(self, character: Character, recipes: list) -> list[tuple[str, list]]:
        """Objets que le joueur peut avoir en stock, par groupe : ressources qu'il récolte (à son niveau), puis
        composants de ses recettes (sauf ceux vendus par les marchands, achetés au besoin)."""
        db = self.site.db
        groups, seen = [], set()
        for key, skill in sorted(character.professions.items()):
            if key not in GATHERING:
                continue
            subclass, skills, label = GATHERING[key]
            rows = [r for r, _, ok in gathering_rows(db.ah_tradeskill_on_sale(subclass), skills, skill) if ok]
            ids = [r["item_id"] for r in rows if r["item_id"] not in seen]
            seen.update(ids)
            if ids:
                groups.append((f"{profession_label(key)} : {label.lower()}", ids))
        reagents = sorted({
            item_id for r in recipes for _, _, item_id in r.reagents or []
            if isinstance(item_id, int) and item_id not in VENDOR_REAGENTS and item_id not in seen
        })
        if reagents:
            groups.append(("Composants de tes recettes", reagents))
        items = db.ah_items_map({i for _, ids in groups for i in ids})
        return [
            (label, sorted((items[i] for i in ids if i in items), key=lambda row: normalize(row["name"])))
            for label, ids in groups
        ]

    async def calculator_page(self, request: web.Request) -> web.Response:
        title = "Calculatrice HdV"
        error, character, picker = self._pick_character(
            request, title, "calculatrice", "/calculatrice",
            "la calculatrice compare la vente de ton stock à ce que tes recettes en feraient.",
        )
        if error is not None:
            return error
        assert character is not None
        recipes = [r for r in self._known_recipes(character) if r.crafted_item_id]
        groups = self._stock_candidates(character, recipes)
        inventory: dict[int, int] = {}
        for key, value in request.query.items():
            if key.startswith("q") and key[1:].isdigit() and value.strip().isdigit():
                inventory[int(key[1:])] = min(int(value), MAX_STOCK)

        inputs = []
        for label, rows in groups:
            cells = "".join(
                f'<label class="stock-item">{item_icon(row)}<span>{item_name(row)}'
                f'<small>{esc(money_text(raw_unit(row))) if raw_unit(row) else "prix inconnu"} l\'unité</small></span>'
                f'<input type="number" name="q{row["id"]}" min="0" max="{MAX_STOCK}" inputmode="numeric" '
                f'value="{inventory.get(row["id"], "")}" placeholder="0"></label>'
                for row in rows
            )
            inputs.append(f'<h3>{esc(label)}</h3><div class="stock-grid">{cells}</div>')
        if not inputs:
            stock_form = (
                '<p class="empty">Rien à saisir : ce perso ne récolte pas de ressource en vente à l\'HdV et ses recettes '
                "n'utilisent pas de composant de l'HdV.</p>"
            )
        else:
            stock_form = f"""<form method="get" action="/calculatrice" class="calc-form" data-perso="{character.id}">
<input type="hidden" name="perso" value="{character.id}">
{"".join(inputs)}
<div class="calc-actions"><button class="act primary">🧮 Calculer</button>
<button type="button" class="act calc-clear">Vider</button></div></form>"""

        result = ""
        if inventory:
            ids = set(inventory) | {r.crafted_item_id for r in recipes}
            ids |= {i for r in recipes for _, _, i in r.reagents or [] if isinstance(i, int)}
            plan = craft_plan(inventory, recipes, self.site.db.ah_items_map(ids))
            result = self._plan_html(plan, bool(recipes))

        no_craft = "" if recipes else (
            '<p class="muted">Ce perso n\'a pas de métier de fabrication : la calculatrice donne la valeur du stock '
            'vendu brut. Pour le faire transformer par un autre joueur, passe par l\'<a href="/atelier">atelier</a>.</p>'
        )
        body = f"""
<h1 class="title">{title}</h1>
<p class="sub">Indique ce que ton perso a en stock : la calculatrice compare la vente brute (au meilleur prix entre
l'<a href="/hdv">HdV</a>, commission de {AH_CUT * 100:.0f} % déduite, et le marchand) avec la fabrication par ses
recettes (composants vendus par les marchands achetés au besoin), aux prix de {self._prices_when()}.
💰 <a href="/rentabilite?perso={character.id}">Rentabilité de ses métiers</a>.</p>
{picker}
{no_craft}
{result}
<h2>Ton stock</h2>
{stock_form}"""
        return self._render(request, title, "calculatrice", body, LIST_SCRIPT + CALC_SCRIPT)

    def _plan_html(self, plan: CraftPlan, can_craft: bool) -> str:
        def item_label(step: CraftStep) -> str:
            product = step.product
            name = item_name(product) if product is not None else esc(step.name)
            return f'<a class="ah-name" href="/hdv/objet/{step.product_id}">{item_icon(product)}<span>{name}</span></a>'

        def steps_table(steps: list[CraftStep], first: str) -> str:
            rows = "".join(
                f"<tr><td>{item_label(s)}</td><td class=\"num\">{number(s.crafts)}</td>"
                f'<td class="num">{esc(money_text(s.product_value))}</td>'
                f'<td class="num muted">{esc(money_text(s.buy_cost)) if s.buy_cost else "—"}</td>'
                f'<td class="num muted">{esc(money_text(s.used_value))}</td><td class="num">{signed_money(s.gain)}</td></tr>'
                for s in steps
            )
            return (
                f'<div class="table-wrap"><table class="ah-table"><thead><tr><th>{first}</th>'
                '<th class="num">Fabrications</th><th class="num">Vente des objets</th><th class="num">Achats marchand</th>'
                '<th class="num">Stock utilisé (valeur brute)</th><th class="num">Gain vs vente brute</th></tr></thead>'
                f"<tbody>{rows}</tbody></table></div>"
            )

        verdict = (
            f'<p class="verdict gain">🛠️ Fabriquer rapporte <b>{esc(money_text(plan.gain))}</b> de plus que tout vendre '
            "brut.</p>" if plan.gain > 0 else
            '<p class="verdict">💰 Mieux vaut tout vendre brut : aucune recette ne rapporte plus que le stock lui-même'
            " aux prix actuels.</p>" if can_craft else ""
        )
        facts = (
            f'<div class="facts"><span class="fact"><small>Tout vendre brut</small><b>{esc(money_text(plan.raw_total))}</b>'
            f'</span><span class="fact"><small>Avec le plan conseillé</small><b>{esc(money_text(plan.total))}</b></span>'
            f'<span class="fact"><small>Différence</small><b>{signed_money(plan.gain)}</b></span></div>'
        )
        parts = [f'<section class="card admin-sec calc-result"><h2>Résultat</h2>{facts}{verdict}']
        if plan.steps:
            parts.append("<h3>Plan conseillé</h3>" + steps_table(plan.steps, "Fabriquer"))
            if plan.leftovers:
                parts.append(
                    f'<p class="muted">Puis vendre brut le reste du stock : {esc(money_text(plan.leftover_value))}.</p>'
                )
        if plan.options:
            parts.append(
                "<h3>Chaque recette seule</h3><p class=\"muted\">Avec tout ton stock pour elle seule ; une même "
                "ressource sert parfois à plusieurs recettes, d'où le plan ci-dessus.</p>"
                + steps_table(plan.options, "Recette")
            )
        elif can_craft:
            parts.append('<p class="muted">Aucune de tes recettes ne peut être fabriquée avec ce stock.</p>')
        if plan.unpriced:
            parts.append(
                f'<p class="muted">⚠️ {len(plan.unpriced)} objet(s) du stock sans prix (ni à l\'HdV ni chez le marchand) '
                "comptent pour 0.</p>"
            )
        parts.append("</section>")
        return "".join(parts)

    # ------------------------------------------------------------ récolte

    def _gathering_section(self, key: str, skill: int | None, level: str) -> str:
        subclass, skills, label = GATHERING[key]
        rows = gathering_rows(self.site.db.ah_tradeskill_on_sale(subclass), skills, skill)
        lines = []
        for row, required, reachable in rows:
            req = str(required) if required is not None else "?"
            value = gathered_value(row)
            vendor = money_text(value.vendor) if value.vendor else "—"
            margin = f"{value.margin:+.0f} %" if value.margin is not None else ""
            lines.append(
                f'<tr class="{"" if reachable else "later"}"><td><a class="ah-name" href="/hdv/objet/{row["item_id"]}">'
                f"{item_icon(row)}<span>{item_name(row)}</span></a></td>"
                f'<td class="num">{req}</td>{money_cells(row["min_price"], row["item_id"])}<td class="gap"></td>'
                f"{money_cells(value.net)}<td class=\"num split muted\">{esc(vendor)}</td>"
                f'<td class="num">{signed_money(value.gain)}</td><td class="num">{esc(margin)}</td>'
                f'<td class="num">{number(row["quantity"])}</td></tr>'
            )
        reachable = sum(1 for r in rows if r[2])
        table = (
            '<div class="table-wrap ah-scroll"><table class="ah-table"><thead>'
            '<tr><th rowspan="2">Ressource</th><th rowspan="2" class="num">Niveau</th>'
            '<th colspan="3" class="group">Prix le plus bas</th><th rowspan="2" class="gap"></th>'
            '<th colspan="3" class="group">Vente HdV (net)</th><th rowspan="2" class="num split">Marchand</th>'
            '<th rowspan="2" class="num">Gain vs marchand</th><th rowspan="2" class="num">Marge</th>'
            '<th rowspan="2" class="num">En vente</th></tr>'
            f'<tr>{COIN_HEADS}{COIN_HEADS}</tr></thead><tbody>{"".join(lines)}</tbody></table></div>'
            if lines else '<p class="empty">Aucune de ces ressources n\'est en vente en ce moment.</p>'
        )
        return f"""<section class="card admin-sec"><h2>{esc(profession_label(key))}{esc(level)} · récolte</h2>
<p class="muted">{esc(label)} en vente à l'HdV{esc(GATHERING_NOTES.get(key, ""))} : {reachable} récoltable(s) à ton niveau (en premier, du plus cher au
moins cher), les autres grisées. Rien à payer pour une ressource récoltée : le gain et la marge comparent la vente à
l'HdV (commission de {AH_CUT * 100:.0f} % déduite) à la revente au marchand ; un gain négatif veut dire qu'il vaut mieux
la vendre au marchand.</p>{table}</section>"""

    # ------------------------------------------------------------ fabrication

    def _crafting_section(self, key: str, recipes: list, level: str) -> str:
        ids = {r.crafted_item_id for r in recipes if r.crafted_item_id}
        ids |= {x[2] for r in recipes for x in r.reagents or [] if x[2]}
        items = self.site.db.ah_items_map(ids)
        results, without_item = recipe_profits(recipes, items)
        lines = []
        for i, r in enumerate(results):
            parts = "".join(
                f"<li>{x.quantity}× {esc(x.name)} : "
                + (f"{esc(money_text(x.total))} <small>({SOURCE_LABELS[x.source]})</small>"
                   if x.total is not None else '<span class="muted">prix inconnu</span>')
                + "</li>"
                for x in r.reagents
            ) or "<li class=\"muted\">aucun composant</li>"
            missing = f' <span class="muted" title="Composants sans prix">+ {r.missing} ?</span>' if r.missing else ""
            product = r.product
            name = item_name(product) if product is not None else esc(r.name)
            icon = item_icon(product) if product is not None else '<span class="ah-icon none"></span>'
            per = f" ×{r.crafted_quantity:g}" if r.crafted_quantity != 1 else ""
            margin = f"{r.margin:+.0f} %" if r.margin is not None else ""
            vendor = money_text(r.vendor_value) if r.vendor_value else "—"
            hidden = " hidden" if i >= SHOWN_RECIPES else ""
            lines.append(
                f'<tr class="{"" if r.revenue is not None else "later"}"{hidden} data-extra="{int(i >= SHOWN_RECIPES)}">'
                f'<td><a class="ah-name" href="/hdv/objet/{r.product_id}">{icon}<span>{name}{esc(per)}</span></a>'
                f'<details class="parts"><summary>{len(r.reagents)} composant(s)</summary><ul>{parts}</ul></details></td>'
                f'{money_cells(r.revenue, r.product_id if r.revenue is not None else None)}<td class="gap"></td>'
                f"{money_cells(r.cost if r.reagents else 0)}<td class=\"num split\">{signed_money(r.profit)}{missing}</td>"
                f'<td class="num">{esc(margin)}</td><td class="num muted">{esc(vendor)}</td>'
                f'<td class="num">{number(r.available) if r.available is not None else "—"}</td></tr>'
            )
        more = len(results) - SHOWN_RECIPES
        more_button = (
            f'<p><button type="button" class="act show-more">Voir les {more} autres recettes</button></p>' if more > 0 else ""
        )
        note = (
            f" {without_item} recette(s) sans objet à vendre (enchantements…) ne sont pas comptées." if without_item else ""
        )
        table = (
            '<div class="table-wrap ah-scroll"><table class="ah-table profit"><thead>'
            '<tr><th rowspan="2">Objet fabriqué</th><th colspan="3" class="group">Vente HdV (net)</th>'
            '<th rowspan="2" class="gap"></th><th colspan="3" class="group">Coût des composants</th>'
            '<th rowspan="2" class="num split">Bénéfice</th><th rowspan="2" class="num">Marge</th>'
            '<th rowspan="2" class="num">Marchand</th><th rowspan="2" class="num">En vente</th></tr>'
            f'<tr>{COIN_HEADS}{COIN_HEADS}</tr></thead><tbody>{"".join(lines)}</tbody></table></div>{more_button}'
            if lines else '<p class="empty">Aucune recette de ce métier ne fabrique d\'objet à vendre.</p>'
        )
        return f"""<section class="card admin-sec"><h2>{esc(profession_label(key))}{esc(level)} · fabrication</h2>
<p class="muted">{len(results)} recette(s) connue(s), de la plus rentable à la moins rentable (bénéfice : vente nette
moins composants). Grisées : objet pas en vente en ce moment. « En vente » : quantité déjà proposée à l'HdV, pour juger
de la concurrence.{esc(note)}</p>{table}</section>"""


PROFIT_SCRIPT = """
<script>
document.querySelectorAll("button.show-more").forEach(b => b.addEventListener("click", () => {
  const section = b.closest("section");
  section.querySelectorAll('tr[data-extra="1"]').forEach(tr => tr.hidden = false);
  b.remove();
}));
</script>
"""

# Calculatrice : le stock saisi est gardé dans le navigateur (par perso), et seuls les champs remplis partent dans
# l'adresse de la page.
CALC_SCRIPT = """
<script>
(() => {
  const form = document.querySelector("form.calc-form");
  if (!form) return;
  const key = "wp-calc-" + form.dataset.perso;
  const inputs = [...form.querySelectorAll("input[type=number]")];
  if (!inputs.some(i => i.value)) {
    try {
      const saved = JSON.parse(localStorage.getItem(key) || "{}");
      inputs.forEach(i => { if (saved[i.name]) i.value = saved[i.name]; });
    } catch (e) {}
  }
  form.addEventListener("submit", () => {
    const data = {};
    inputs.forEach(i => { if (+i.value > 0) data[i.name] = i.value; else i.disabled = true; });
    try { localStorage.setItem(key, JSON.stringify(data)); } catch (e) {}
  });
  form.querySelector(".calc-clear").addEventListener("click", () => {
    inputs.forEach(i => { i.value = ""; });
    try { localStorage.removeItem(key); } catch (e) {}
  });
})();
</script>
"""
