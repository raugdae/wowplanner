"""Page « Rentabilité » : ce que rapportent les métiers d'un de ses persos, aux prix de l'hôtel des ventes.

Calculs dans profit.py ; prix et catalogue des objets dans la base locale (cogs/auctions.py).
"""
from __future__ import annotations

from datetime import datetime

from aiohttp import web

from .auctions import money_text
from .gamedata import is_primary, profession_label
from .profit import AH_CUT, GATHERING, gathered_value, gathering_rows, recipe_profits
from .web import _VIEWER, esc
from .webauction import COIN_HEADS, LIST_SCRIPT, AuctionPages, item_icon, item_name, money_cells, number

# Au-delà, les recettes les moins rentables sont repliées.
SHOWN_RECIPES = 40


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
    def register_profit(self, router: web.UrlDispatcher) -> None:
        router.add_get("/rentabilite", self.profit_page)

    async def profit_page(self, request: web.Request) -> web.Response:
        title = "Rentabilité de mes métiers"
        if not self.house:
            return self._disabled(request)
        viewer = _VIEWER.get()
        user = self._web_user()
        if user is None or viewer is None:
            body = (
                f'<h1 class="title">{title}</h1><p class="muted">Connexion Discord nécessaire : la page montre ce '
                "que rapportent les métiers de tes persos.</p>"
            )
            return self._render(request, title, "rentabilite", body)
        db = self.site.db
        crafters = [c for c in viewer.characters if c.professions]
        if not crafters:
            body = (
                f'<h1 class="title">{title}</h1><p class="empty">Aucun de tes persos n\'a de métier connu. Les métiers '
                'viennent de l\'armurerie : ajoute tes persos dans <a href="/mes-persos">Mes persos</a>.</p>'
            )
            return self._render(request, title, "rentabilite", body)

        wanted = request.query.get("perso", "")
        character = next((c for c in crafters if str(c.id) == wanted), None)
        if character is None:
            character = next((c for c in crafters if c.favorite), crafters[0])
        picker = "".join(
            f'<option value="{c.id}"{" selected" if c.id == character.id else ""}>{"⭐ " if c.favorite else ""}'
            f'{esc(c.name)} — {esc(", ".join(profession_label(p) for p in c.professions))}</option>'
            for c in crafters
        )

        gid = self.site.guild_id()
        known = db.character_recipe_ids(character.id)
        sections = []
        professions = sorted(character.professions.items(), key=lambda p: (not is_primary(p[0]), p[0]))
        for key, skill in professions:
            level = f" · niveau {skill}" if skill is not None else ""
            if key in GATHERING:
                sections.append(self._gathering_section(key, skill, level))
            recipes = [r for r in db.guild_recipes(gid, key) if r.id in known] if gid is not None else []
            if recipes:
                sections.append(self._crafting_section(key, recipes, level))
            elif key not in GATHERING:
                sections.append(
                    f'<section class="card admin-sec"><h2>{esc(profession_label(key))}{esc(level)}</h2>'
                    '<p class="empty">Aucune recette connue dans l\'armurerie pour ce perso.</p></section>'
                )

        snapshot = db.ah_snapshot_time()
        when = f"{datetime.fromtimestamp(snapshot, self.tz):%H:%M le %d/%m}" if snapshot else "pas encore relevés"
        body = f"""
<h1 class="title">{title}</h1>
<p class="sub">Ce que rapportent les métiers de ton perso aux prix de l'<a href="/hdv">hôtel des ventes</a>
(n° {self.house}, prix de {when}). Vente au prix le plus bas actuel, commission de {AH_CUT * 100:.0f} % déduite ;
composants au prix le plus bas de l'HdV, ou au prix du marchand pour ceux qu'il vend (fioles, fils, teintures, flux,
épices…). « Marchand » : ce que le marchand te donne pour l'objet.</p>
<form method="get" action="/rentabilite" class="filters"><select name="perso" data-autosubmit aria-label="Perso">{picker}</select>
<noscript><button class="act">Voir</button></noscript></form>
{"".join(sections)}"""
        return self._render(request, title, "rentabilite", body, LIST_SCRIPT + PROFIT_SCRIPT)

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
<p class="muted">{esc(label)} en vente à l'HdV : {reachable} récoltable(s) à ton niveau (en premier, du plus cher au
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
