"""Captures d'écran de la page d'aide, prises sur le site de démo (demo_server.py) avec Playwright.

Écrit wowplanner/static/aide/<nom>.webp et shots.json (taille en px CSS, et pour chaque repère la zone désignée,
en % de l'image : x, y, largeur, hauteur). Voir README, « Page d'aide ».
Usage : python tools/aide/captures.py http://127.0.0.1:8766 [nom…]   (sans nom : toutes les captures)
Navigateur : CHROME_PATH (ex. Chrome installé), sinon le Chromium de Playwright (playwright install chromium).
"""
import asyncio
import io
import json
import os
import sys
from pathlib import Path

from PIL import Image
from playwright.async_api import async_playwright

BASE = sys.argv[1].rstrip("/")
ONLY = set(sys.argv[2:])
OUT = Path(__file__).resolve().parents[2] / "wowplanner" / "static" / "aide"
CHROME = os.getenv("CHROME_PATH") or None
STATIC_HEADER = "header{position:static !important}"


async def union_box(page, selectors, pad):
    boxes = []
    for sel in selectors:
        loc = page.locator(sel).first
        await loc.wait_for(state="visible", timeout=8000)
        b = await loc.bounding_box()
        boxes.append(b)
    sx, sy = await page.evaluate("[scrollX, scrollY]")
    x0 = min(b["x"] for b in boxes) - pad
    y0 = min(b["y"] for b in boxes) - pad
    x1 = max(b["x"] + b["width"] for b in boxes) + pad
    y1 = max(b["y"] + b["height"] for b in boxes) + pad
    width = await page.evaluate("document.documentElement.scrollWidth")
    return {"x": max(0, x0 + sx), "y": max(0, y0 + sy), "width": min(x1, width) - max(0, x0), "height": y1 - max(0, y0)}


async def spot(page, sel, clip):
    loc = page.locator(sel).first
    if not await loc.count():
        print("   ! repère introuvable :", sel)
        return None
    b = await loc.bounding_box()
    if b is None:
        print("   ! repère invisible :", sel)
        return None
    sx, sy = await page.evaluate("[scrollX, scrollY]")
    x0 = max(b["x"] + sx, clip["x"]) - clip["x"]
    y0 = max(b["y"] + sy, clip["y"]) - clip["y"]
    x1 = min(b["x"] + sx + b["width"], clip["x"] + clip["width"]) - clip["x"]
    y1 = min(b["y"] + sy + b["height"], clip["y"] + clip["height"]) - clip["y"]
    if x1 <= x0 or y1 <= y0:
        print("   ! repère hors de l'image :", sel)
        return None
    W, H = clip["width"], clip["height"]
    return [round(x0 / W * 100, 2), round(y0 / H * 100, 2), round((x1 - x0) / W * 100, 2), round((y1 - y0) / H * 100, 2)]


SHOTS = []


def shot(name, url, clip, spots=None, prep=None, pad=12, max_h=None, viewport=(1280, 860), login=True,
         static_header=True, dsf=1):
    SHOTS.append(dict(name=name, url=url, clip=clip if isinstance(clip, list) else [clip], spots=spots or {},
                      prep=prep, pad=pad, max_h=max_h, viewport=viewport, login=login,
                      static_header=static_header, dsf=dsf))


# ------------------------------------------------------------------ préparations

async def open_menu(page):
    await page.click("details.usermenu summary")


async def open_new_event(page):
    await page.click("#nouvelle summary")
    await page.fill("input[name=instance]", "Les Mortemines")


async def hover_item(page):
    await page.hover(".armory .slot:not(.empty) >> nth=0")
    await page.wait_for_timeout(300)


async def hover_stat(page):
    await page.hover(".statbox .srow[tabindex] >> nth=3")
    await page.wait_for_timeout(300)


async def open_gear(page):
    await page.click("#equipement-fabricable summary")
    await page.wait_for_timeout(200)


async def scroll_recipes(page):
    await page.locator(".tabs").first.scroll_into_view_if_needed()


async def order_form(page):
    await page.goto(BASE + "/atelier?q=e")
    await page.click(".order-link >> nth=0")
    await page.wait_for_selector("#commande")


async def hover_price(page):
    cell = page.locator(".ah-table tbody tr >> nth=2").locator("a.price[data-item] >> nth=0")
    await cell.hover()
    await page.wait_for_selector(".spark-pop:not([hidden])", timeout=8000)
    await page.wait_for_timeout(400)


async def item_page(page):
    await page.goto(BASE + "/hdv?favoris=1")
    await page.click(".ah-name >> nth=0")
    await page.wait_for_selector(".price-chart")
    await page.wait_for_timeout(400)


STOCK = {"Pacifique": 40, "Feuillargent": 25, "Mage royal": 18, "Etouffante": 12, "Fiole vide": 20, "Terrestrine": 8,
         "Aciérite sauvage": 6}


async def fill_stock(page):
    for name, qty in STOCK.items():
        row = page.locator("tr", has=page.locator(f"text='{name}'")).first
        if await row.count():
            await row.locator("input[type=number]").fill(str(qty))
    await page.click("button:has-text('Calculer')")
    await page.wait_for_selector(".calc-result")


async def calc_stock(page):
    await fill_stock(page)
    box = page.locator(".calc-mine")
    await box.check()
    await page.wait_for_timeout(200)
    await page.locator(".calc-tools").scroll_into_view_if_needed()


async def dungeon_level(page):
    await page.fill("#lvl", "24")
    await page.dispatch_event("#lvl", "input")


# ------------------------------------------------------------------ liste des captures

shot("connexion", "/", ".login-box", {"btn": ".login-box .btn"}, login=False, pad=24)
shot("barre", "/sorties", "header", {
    "brand": "header .brand", "sorties": "header nav a[href='/sorties']", "guilde": "header nav a[href='/']",
    "metiers": "header nav a[href='/metiers']", "atelier": "header nav a[href='/atelier']",
    "hdv": "header nav a[href='/hdv']", "donjons": "header nav a[href='/donjons']", "aide": "header nav a[href='/aide']",
    "menu": "details.usermenu summary"}, pad=0, static_header=False)
shot("menu", "/sorties", ["details.usermenu summary", ".menu-panel"], {
    "chars": ".menu-char", "gerer": ".menu-link[href='/mes-persos']", "rentab": ".menu-link[href='/rentabilite']",
    "calc": ".menu-link[href='/calculatrice']", "theme": "#theme", "admin": ".menu-link[href='/admin']",
    "logout": ".menu-link[href='/auth/logout']"}, prep=open_menu, pad=16, static_header=False)
shot("sortie", "/sorties", "#s1001", {
    "titre": "#s1001 .ev-head h3", "discord": "#s1001 .ev-head a[target]", "roles": "#s1001 .ev-role >> nth=1",
    "perso": "#s1001 select.pick", "boutons": "#s1001 button[value=heal]"})
shot("sortie-inscrit", "/sorties", "#s1002", {
    "moi": "#s1002 li.me", "changer": "#s1002 select.pick", "quitter": "#s1002 form[action$=quitter] button",
    "annuler": "#s1002 form[action$=annuler] button", "retirer": "#s1002 button.x"})
shot("nouvelle-sortie", "/sorties", "#nouvelle", {
    "instance": "input[name=instance]", "date": "input[name=date]", "heure": "input[name=heure]",
    "nombres": "input[name=tanks]", "desc": "textarea[name=description]", "bouton": "#nouvelle button.primary"},
     prep=open_new_event)
shot("guilde", "/", ["main h1", "main .filters", "main tbody tr >> nth=5"], {
    "q": "#q", "classe": "select[data-filter=classe]", "role": "select[data-filter=role]",
    "metier": "select[data-filter=metier]", "perso": "main tbody tr >> nth=2 >> a.who-cell",
    "metiers": "main tbody tr >> nth=1 >> td >> nth=5"})
shot("fiche", "/perso/1", ["main h1", ".armory .doll", ".statbox h4 >> nth=0"], {
    "titre": "main p.sub", "objet": ".armory .slot:not(.empty) >> nth=0", "rendu": ".armory .center",
    "spe": "#spec", "prio": ".prio-box .chips:not([hidden])", "stats": ".statbox .srow >> nth=0"})
shot("infobulle-objet", "/perso/1", [".armory .slot:not(.empty) >> nth=0", ".armory .slot:not(.empty) >> nth=0 >> .tt"],
     prep=hover_item, pad=10)
shot("infobulle-stat", "/perso/1", [".statbox .srow[tabindex] >> nth=3", ".statbox .srow[tabindex] >> nth=3 >> .tt"],
     prep=hover_stat, pad=10)
shot("talents", "/perso/1", ".talents", {"arbre": ".tree-head >> nth=2", "talent": ".tree >> nth=2 >> .tal >> nth=2"})
shot("equipement", "/perso/1", ["#equipement-fabricable summary", "#equipement-fabricable .gear-group >> nth=1"], {
    "case": "#gear-only-up", "groupe": ".gear-group h4 >> nth=0", "carte": ".gear-list > * >> nth=0"}, prep=open_gear)
shot("recettes", "/perso/1", ["main h2:has-text('Recettes')", "[data-panel]:not([hidden]) details.fold >> nth=2"], {
    "q": "#q", "plier": "button[data-fold=open]", "onglets": ".tabs button >> nth=0",
    "famille": "[data-panel]:not([hidden]) details.fold summary >> nth=0"}, prep=scroll_recipes)
shot("mes-persos", "/mes-persos", ["main h1", "main form.form"], {
    "etoile": "button.fav", "role": "select.pick", "supprimer": "button.danger", "nom": "#new-name",
    "ajouter": "#new-submit"})
shot("metiers", "/metiers", ["main h1", ".grid"], {"tuile": ".tile >> nth=0"})
shot("commande", "/atelier", "#commande", {
    "recette": "#commande .card", "artisan": "select[name=artisan]", "quantite": "input[name=quantite]",
    "mot": "textarea[name=note]", "envoyer": "#commande button.primary"}, prep=order_form)
shot("atelier", "/atelier", ["main h2:has-text('Commander un objet')", "main table >> nth=-1"], {
    "recherche": "input[name=q]", "recues": "h3:has-text('demandé')", "passees": "h3:has-text('commandé')"})
shot("hdv", "/hdv", ["main h1", ".ah-table tbody tr >> nth=4"], {
    "q": ".ah-filters input[name=q]", "type": "select[name=classe]", "tri": "select[name=tri]", "fav": ".fav-filter",
    "etoile": ".ah-table tbody tr >> nth=0 >> button.fav", "bas": ".ah-table thead th.group >> nth=0",
    "median": ".ah-table thead th.group >> nth=1", "dispo": ".ah-table thead th.split", "var": ".ah-table thead th >> nth=7"})
shot("hdv-survol", "/hdv", [".ah-table tbody tr >> nth=2 >> a.price[data-item] >> nth=0", ".spark-pop"], prep=hover_price, pad=30)
shot("hdv-objet", "/hdv", ["main h1", ".chart-wrap"], {
    "periode": "main a.act.on", "courbe": ".price-chart"}, prep=item_page)
shot("rentabilite", "/rentabilite", ["main h1", "[data-panel]:not([hidden]) tbody tr >> nth=6"], {
    "perso": "select[name=perso]", "onglets": ".tabs button >> nth=0",
    "vente": "[data-panel]:not([hidden]) th.group >> nth=0", "cout": "[data-panel]:not([hidden]) th.group >> nth=1",
    "benef": "[data-panel]:not([hidden]) th.split"})
shot("calc-stock", "/calculatrice", [".calc-tools", ".calc-table tbody tr:not([hidden]) >> nth=5"], {
    "cat": ".calc-category", "q": ".calc-search", "mine": ".calc-mine", "qte": ".calc-table td.qty input >> nth=0",
    "calc": ".calc-tools button.primary"}, prep=calc_stock)
shot("calc-resultat", "/calculatrice", ".calc-result", {"faits": ".calc-result .facts, .calc-result h2",
     "plan": ".calc-result h3 >> nth=0"}, prep=fill_stock, max_h=640)
shot("donjons", "/donjons", ["main h1", "#dungeons tbody tr >> nth=8"], {
    "q": "#q", "perso": "#lvl-who", "niveau": "#lvl", "tranche": "#lvl-only", "ligne": "#dungeons tr.d-in >> nth=0",
    "barre": "#dungeons tr.d-in >> nth=0 >> .lbar", "qui": "#dungeons tr.d-in >> nth=0 >> .who-avatars"},
     prep=dungeon_level)
shot("donjon", "/donjon/the-deadmines", ["main .crumb", ".route .step >> nth=4"], {
    "faits": ".facts", "creer": ".create-ev", "entree": ".dgrid .card >> nth=0 >> p >> nth=0", "way": "button.copy",
    "guide": ".dgrid a.btn[target]", "qui": ".who-list", "route": ".route .step >> nth=1"})
shot("admin", "/admin", ["main h1", "#persos tbody tr >> nth=3"], {
    "sync": "form[action='/admin/sync'] button", "q": "#persos #q", "role": "#persos select.pick",
    "suppr": "#persos button.danger"})
shot("mobile", "/sorties", ["header", "#s1001 .ev-role >> nth=0"], {"nav": "header nav", "menu": "details.usermenu summary"},
     viewport=(390, 844), pad=0, static_header=False, dsf=2)


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    index_path = OUT / "shots.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=CHROME)
        for s in SHOTS:
            if ONLY and s["name"] not in ONLY:
                continue
            print("•", s["name"])
            ctx = await browser.new_context(viewport={"width": s["viewport"][0], "height": s["viewport"][1]},
                                            device_scale_factor=s["dsf"], locale="fr-FR")
            page = await ctx.new_page()
            if s["login"]:
                await page.goto(BASE + "/auth/demo?next=/donjons")
            await page.goto(BASE + s["url"], wait_until="networkidle")
            if s["static_header"]:
                await page.add_style_tag(content=STATIC_HEADER)
            await page.add_style_tag(content="*{scrollbar-width:none !important} ::-webkit-scrollbar{display:none}")
            if s["prep"]:
                await s["prep"](page)
                # La préparation peut avoir changé de page : on réapplique les styles de capture.
                if s["static_header"]:
                    await page.add_style_tag(content=STATIC_HEADER)
                await page.add_style_tag(content="*{scrollbar-width:none !important} ::-webkit-scrollbar{display:none}")
            await page.wait_for_timeout(250)
            clip = await union_box(page, s["clip"], s["pad"])
            if s["max_h"]:
                clip["height"] = min(clip["height"], s["max_h"])
            spots = {}
            for key, sel in s["spots"].items():
                pos = None
                for alt in sel.split(", ") if sel.count(", ") and "has-text" not in sel else [sel]:
                    pos = await spot(page, alt, clip)
                    if pos:
                        break
                if pos:
                    spots[key] = pos
            png = await page.screenshot(clip=clip, full_page=True)
            img = Image.open(io.BytesIO(png))
            img.save(OUT / f"{s['name']}.webp", "WEBP", quality=82, method=6)
            index[s["name"]] = {"w": round(clip["width"]), "h": round(clip["height"]), "spots": spots}
            index_path.write_text(json.dumps(index, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
            print("  ", img.size, f"{(OUT / (s['name'] + '.webp')).stat().st_size // 1024} Ko", len(spots), "repère(s)")
            await ctx.close()
        await browser.close()
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


asyncio.run(main())
