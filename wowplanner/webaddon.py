"""Page « Addon WoW » (jeton du client local, téléchargements, ce que le site a reçu du jeu) et API du client.

API (jeton dans l'en-tête « Authorization: Bearer wp_… ») :
- GET  /api/addon/moi        : à qui appartient le jeton, ses persos (test de connexion du client) ;
- GET  /api/addon/prix       : prix de l'HdV pour Data.lua (ETag : rien n'est renvoyé si rien n'a changé) ;
- POST /api/addon/inventaire : ce que l'addon a vu en jeu (voir addon.parse_inventory).
Voir addon.py pour le fonctionnement d'ensemble.
"""
from __future__ import annotations

import hmac
import io
import json
import logging
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aiohttp import web

from .addon import PayloadError, hash_token, match_recipes, new_token, parse_inventory
from .webauth import MEMBER_RECHECK_SECONDS
from .weblegal import REPO
from .webui import COPY_SCRIPT, _VIEWER, esc

if TYPE_CHECKING:
    from .web import WebSite
    from .webmember import MemberPages

log = logging.getLogger(__name__)

# Dossier de l'addon (à la racine du dépôt ; copié dans l'image Docker).
ADDON_DIR = Path(__file__).resolve().parent.parent / "addon" / "WowPlanner"
CLIENT_URL = f"{REPO}/releases/latest"


def addon_zip() -> bytes | None:
    """L'addon en .zip (dossier WowPlanner/ prêt à poser dans Interface/AddOns), None s'il est absent."""
    if not ADDON_DIR.is_dir():
        return None
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(ADDON_DIR.rglob("*")):
            if path.is_file():
                archive.write(path, Path("WowPlanner") / path.relative_to(ADDON_DIR))
    return buffer.getvalue()


class AddonPages:
    def __init__(self, site: WebSite, pages: MemberPages):
        self.site = site
        self.pages = pages  # pour la mise en page, les jetons de formulaire et les messages
        self._zip: bytes | None = None

    def register(self, router: web.UrlDispatcher) -> None:
        router.add_get("/addon", self.addon_page)
        router.add_post("/addon/jeton", self.create_token)
        router.add_post("/addon/jeton/supprimer", self.delete_token)
        router.add_get("/addon/WowPlanner.zip", self.download)
        router.add_get("/api/addon/moi", self.api_me)
        router.add_get("/api/addon/prix", self.api_prices)
        router.add_post("/api/addon/inventaire", self.api_inventory)

    # ============================================================ page

    def _when(self, ts: int | None) -> str:
        if not ts:
            return "jamais"
        return datetime.fromtimestamp(ts, self.pages.tz).strftime("%d/%m/%Y à %H:%M")

    async def addon_page(self, request: web.Request, token: str = "") -> web.Response:
        db = self.site.db
        user = self.pages._web_user()
        title = "Addon WoW"
        if user is None or not user.id:
            body = f'<h1 class="title">{title}</h1><p class="muted">Connexion Discord nécessaire pour utiliser l\'addon.</p>'
            return self.pages._render(request, title, "", body)
        row = db.addon_token(user.id)
        csrf = self.pages._csrf_field()
        if token:
            key_block = f"""<div class="flash" role="status"><p><b>Ton jeton</b> (affiché une seule fois : copie-le
maintenant dans le client WoW Planner) :</p>
<p class="token-line"><code>{esc(token)}</code> <button type="button" class="act" data-copy="{esc(token)}"><span>Copier</span>
</button></p><p class="muted">Garde-le pour toi : il permet de lire les prix et d'envoyer l'inventaire de tes persos.</p></div>"""
        elif row:
            key_block = (
                f'<p>Jeton créé le {self._when(row["created_at"])}, dernière utilisation : '
                f'{self._when(row["last_used_at"])}.</p>'
            )
        else:
            key_block = "<p>Tu n'as pas encore de jeton.</p>"
        label = "Créer un nouveau jeton (l'ancien ne marchera plus)" if row else "Créer mon jeton"
        buttons = (
            f'<form method="post" action="/addon/jeton" class="inline">{csrf}<button class="act" type="submit">'
            f"{label}</button></form>"
        )
        if row:
            buttons += (
                f' <form method="post" action="/addon/jeton/supprimer" class="inline">{csrf}'
                '<button class="act danger" type="submit">Supprimer le jeton</button></form>'
            )

        lines = []
        for c in _VIEWER.get().characters if _VIEWER.get() else []:
            meta, items = db.game_inventory(c.id)
            if meta is None:
                continue
            bank = f"banque vue le {self._when(meta['bank_at'])}" if meta["bank_at"] else "banque jamais ouverte"
            lines.append(
                f"<tr><td><b>{esc(c.name)}</b></td><td>{self._when(meta['updated_at'])}</td><td>{bank}</td>"
                f'<td class="num">{len(items)}</td>'
                f'<td><a href="/calculatrice?perso={c.id}&amp;jeu=1">Calculatrice avec ce stock →</a></td></tr>'
            )
        received = (
            '<div class="table-wrap"><table><thead><tr><th>Perso</th><th>Dernier relevé</th><th>Banque</th>'
            f'<th class="num">Objets</th><th></th></tr></thead><tbody>{"".join(lines)}</tbody></table></div>'
            if lines else '<p class="muted">Rien reçu du jeu pour l\'instant.</p>'
        )
        body = f"""
<h1 class="title">🧩 Addon WoW</h1>
<p class="sub">Les prix de l'hôtel des ventes dans les infobulles du jeu, et ton inventaire (sacs, banque), tes
métiers et tes recettes envoyés au site pour la calculatrice.</p>
<section class="card admin-sec"><h2>1. Installer</h2>
<ol>
<li>Télécharge le <a href="{CLIENT_URL}" target="_blank" rel="noopener">client WoW Planner</a> (Windows ou macOS) et
lance-le.</li>
<li>Dans le client, choisis le dossier du jeu (celui qui contient <code>Interface</code> et <code>WTF</code>) :
le client y installe l'addon tout seul.</li>
<li>Colle ton jeton (ci-dessous) dans le client.</li>
</ol>
<p class="muted">Sans le client, tu peux poser l'addon à la main : <a href="/addon/WowPlanner.zip">WowPlanner.zip</a>, à
décompresser dans <code>Interface/AddOns</code>. Il n'aura alors pas les prix ni l'envoi de l'inventaire.</p>
</section>
<section class="card admin-sec"><h2>2. Ton jeton</h2>{key_block}<div class="actions">{buttons}</div></section>
<section class="card admin-sec"><h2>3. En jeu</h2>
<ul>
<li>Survole un objet : prix le plus bas, prix médian et ventes estimées par jour à l'HdV.</li>
<li><code>/wp</code> : date des prix et état de l'addon. <code>/wp maj</code> : recharge l'interface pour prendre les
derniers prix téléchargés par le client.</li>
<li>Ouvre ta banque et chacune de tes fenêtres de métier une fois : l'addon les note pour le site.</li>
</ul>
<p class="muted">Le jeu n'enregistre ce que voit l'addon qu'à la déconnexion ou au <code>/reload</code> : le client
l'envoie au site juste après.</p>
</section>
<section class="card admin-sec"><h2>Reçu du jeu</h2>{received}</section>"""
        return self.pages._render(request, title, "", body, COPY_SCRIPT)

    def _form_ok(self, request: web.Request, form: Any, user_id: int) -> bool:
        return self.pages._same_origin(request) and hmac.compare_digest(
            str(form.get("csrf", "")), self.pages.csrf_token(user_id)
        )

    async def create_token(self, request: web.Request) -> web.StreamResponse:
        user = self.pages._web_user()
        if user is None or not user.id:
            raise web.HTTPForbidden(text="Connexion Discord nécessaire.")
        form = await request.post()
        if not self._form_ok(request, form, user.id):
            response = self.site._redirect("/addon")
            self.pages._set_flash(response, "Formulaire expiré : recharge la page et recommence.", False)
            return response
        token = new_token()
        self.site.db.set_addon_token(user.id, hash_token(token), int(time.time()))
        log.info("Addon : nouveau jeton pour %s", user.id)
        response = await self.addon_page(request, token)
        response.headers["Cache-Control"] = "no-store"
        return response

    async def delete_token(self, request: web.Request) -> web.StreamResponse:
        user = self.pages._web_user()
        if user is None or not user.id:
            raise web.HTTPForbidden(text="Connexion Discord nécessaire.")
        form = await request.post()
        response = self.site._redirect("/addon")
        if not self._form_ok(request, form, user.id):
            self.pages._set_flash(response, "Formulaire expiré : recharge la page et recommence.", False)
        elif self.site.db.delete_addon_token(user.id):
            self.pages._set_flash(response, "Jeton supprimé : le client ne peut plus rien lire ni envoyer.", True)
        return response

    async def download(self, request: web.Request) -> web.Response:
        if self._zip is None:
            self._zip = addon_zip()
        if not self._zip:
            raise web.HTTPNotFound(text="Addon introuvable sur ce serveur.")
        return web.Response(
            body=self._zip, content_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="WowPlanner.zip"'},
        )

    # ============================================================ API

    @staticmethod
    def _error(status: int, text: str) -> web.Response:
        return web.json_response({"error": text}, status=status)

    async def _owner(self, request: web.Request) -> int | web.Response:
        """Joueur du jeton (en-tête Authorization), ou la réponse d'erreur à renvoyer."""
        header = request.headers.get("Authorization", "")
        token = header[7:].strip() if header.lower().startswith("bearer ") else ""
        row = self.site.db.addon_token_owner(hash_token(token)) if token else None
        if row is None:
            return self._error(401, "Jeton inconnu : crée-en un sur la page Addon WoW du site.")
        user_id, now = int(row["user_id"]), int(time.time())
        checked = False
        if self.site._is_member is not None and now - (row["checked_at"] or 0) > MEMBER_RECHECK_SECONDS:
            member = await self.site._is_member(user_id)
            if member is False:
                return self._error(403, "Tu n'es plus membre du serveur Discord.")
            checked = member is True
        self.site.db.touch_addon_token(user_id, now, checked)
        return user_id

    async def api_me(self, request: web.Request) -> web.Response:
        owner = await self._owner(request)
        if isinstance(owner, web.Response):
            return owner
        characters = self.site.db.get_characters(owner)
        return web.json_response({"characters": [c.name for c in characters]})

    async def api_prices(self, request: web.Request) -> web.Response:
        owner = await self._owner(request)
        if isinstance(owner, web.Response):
            return owner
        db = self.site.db
        snapshot = db.ah_snapshot_time() or 0
        cover = db.conn.execute("SELECT MAX(ts) FROM ah_sales_cover").fetchone()[0] or 0
        etag = f'"{snapshot}-{cover}"'
        if request.headers.get("If-None-Match") == etag:
            return web.Response(status=304, headers={"ETag": etag})
        now = int(time.time())
        data = {"ts": snapshot, "generated": now, "items": [list(r) for r in db.addon_prices(now)]}
        response = web.Response(
            text=json.dumps(data, separators=(",", ":")), content_type="application/json", headers={"ETag": etag}
        )
        response.enable_compression()
        return response

    async def api_inventory(self, request: web.Request) -> web.Response:
        owner = await self._owner(request)
        if isinstance(owner, web.Response):
            return owner
        try:
            received = parse_inventory(await request.json())
        except PayloadError as exc:
            return self._error(400, str(exc))
        except ValueError:
            return self._error(400, "JSON illisible.")
        db = self.site.db
        mine = {c.name.casefold(): c for c in db.get_characters(owner)}
        updated, unknown, unmatched = [], [], 0
        for game in received:
            character = mine.get(game.name.casefold())
            if character is None:
                unknown.append(game.name)
                continue
            recipe_ids: set[int] | None = None
            if game.recipes is not None:
                recipe_ids = set()
                for profession, seen in game.recipes.items():
                    ids, missing = match_recipes(seen, db.recipes_of_profession(profession))
                    recipe_ids |= ids
                    unmatched += missing
            db.store_game_character(
                character.id, level=game.level, money=game.money, updated_at=game.updated_at or int(time.time()),
                bags=game.bags, bank=game.bank, bank_at=game.bank_at, professions=game.professions,
                recipe_ids=recipe_ids,
            )
            updated.append(character.name)
        if updated:
            log.info("Addon : inventaire reçu pour %s (%s)", owner, ", ".join(updated))
        return web.json_response({"updated": updated, "unknown": unknown, "unmatched_recipes": unmatched})
