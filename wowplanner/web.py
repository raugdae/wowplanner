"""Serveur du site : connexion avec Discord, contrôle d'accès, routes, feuille de style.

Les pages sont ailleurs :
- webpages.py : consultation (Guilde, fiche d'un perso, Métiers, Donjons) ;
- webmember.py : Sorties, Mes persos, Atelier, Administration ;
- webauction.py : Hôtel des ventes ; webprofit.py : Rentabilité de mes métiers, Calculatrice HdV ;
- webui.py (mise en page commune), webcharacter.py et webrecipes.py (blocs HTML), static/site.css (style).

Avec DISCORD_CLIENT_SECRET, le site est réservé aux membres du serveur Discord (connexion Discord, voir
webauth.py), sauf les pages Donjons (publiques, sans les persos du serveur) et la feuille de style. Les membres
connectés peuvent agir (sorties, persos, atelier…) : les actions sont exécutées par le bot (cogs/webbridge.py).

Servi par aiohttp dans le même processus que le bot (même base SQLite). Activé par WEB_PORT ; derrière
Traefik en production (voir docker-compose.traefik.yml).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import secrets
import time
from collections import deque
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

from aiohttp import web

from .db import Database
from .webauth import (
    MEMBER_RECHECK_SECONDS,
    SESSION_COOKIE,
    SESSION_SECONDS,
    STATE_COOKIE,
    STATE_SECONDS,
    DiscordOAuth,
    OAuthError,
    safe_next,
    sign,
    unsign,
)
from .webhelp import HelpPages
from .weblegal import LegalPages
from .webaddon import AddonPages
from .webpages import GuildPages
from .webprofit import ProfitPages
from .webui import (
    _VIEWER,
    Viewer,
    esc,
    login_url,
    page,
)

log = logging.getLogger(__name__)


# Pages visibles sans connexion (sans les persos du serveur) ; l'aide ne montre que des données d'exemple.
PUBLIC_PATHS = ("/donjons", "/donjon/", "/aide", "/conditions", "/confidentialite", "/auth/", "/static/", "/favicon.ico",
                "/api/addon/")

# Accès invité : au-delà de 10 mots de passe faux en 15 minutes (tous visiteurs confondus), on refuse.
GUEST_MAX_FAILURES = 10
GUEST_FAIL_WINDOW = 15 * 60


STYLESHEET = (Path(__file__).parent / "static" / "site.css").read_text(encoding="utf-8")
LOGO = (Path(__file__).parent / "static" / "logo.svg").read_bytes()


class WebSite:
    def __init__(self, db: Database, guild_id: Callable[[], int | None]):
        self.db = db
        self._guild_id = guild_id
        self._runner: web.AppRunner | None = None
        # Connexion Discord (voir enable_auth) ; None = site ouvert à tous.
        self.oauth: DiscordOAuth | None = None
        self._secret = b""
        self._is_member: Callable[[int], Awaitable[bool | None]] | None = None
        self._secure_cookies = True
        # Actions des membres (sorties, persos), exécutées par le bot : voir cogs/webbridge.py et webmember.py.
        self.actions: Any = None
        # Hôtel des ventes suivi (AUCTION_HOUSE_ID) ; 0 = page Hôtel des ventes désactivée.
        self.auction_house = 0
        # Accès invité (voir enable_guest) : clé du lien caché et mot de passe ; vides = désactivé.
        self._guest_key = ""
        self._guest_password = ""
        self._guest_as = ""
        self._guest_failures: deque[float] = deque()

    def enable_guest(self, key: str, password: str, as_who: str = "") -> None:
        """Accès en lecture seule sans Discord : lien /auth/invite/<key> (introuvable sans la clé) + mot de passe.
        Changer le mot de passe déconnecte les invités déjà connectés.

        `as_who` (identifiant Discord ou nom d'un perso) : l'invité voit le site comme ce joueur (ses persos, sa
        rentabilité, ses favoris, l'administration s'il y a droit), toujours sans pouvoir rien modifier."""
        self._guest_key, self._guest_password, self._guest_as = key, password, as_who.strip()

    def _guest_user_id(self) -> int:
        """Joueur dont l'invité emprunte le point de vue (0 = aucun). Relu à chaque page : suit les renommages."""
        who = self._guest_as
        if who.isdigit():
            return int(who)
        if who:
            wanted = who.casefold()
            for c in self.db.all_characters():
                if c.name.casefold() == wanted:
                    return c.user_id
            log.warning("GUEST_AS : aucun perso nommé %r", who)
        return 0

    def _guest_print(self) -> str:
        """Empreinte du mot de passe invité gardée dans la session : un autre mot de passe l'invalide."""
        return hmac.new(self._secret, f"guest:{self._guest_password}".encode(), hashlib.sha256).hexdigest()[:16]

    def _guest_ok(self, user: dict[str, Any]) -> bool:
        return bool(self._guest_password) and secrets.compare_digest(str(user.get("g", "")), self._guest_print())

    def enable_actions(self, actions: Any) -> None:
        self.actions = actions

    def enable_auth(
        self,
        oauth: DiscordOAuth,
        secret: bytes,
        is_member: Callable[[int], Awaitable[bool | None]],
        secure_cookies: bool = True,
    ) -> None:
        """Réserve le site aux membres du serveur. `is_member(id)` : True / False, ou None si on ne sait pas."""
        self.oauth, self._secret, self._is_member = oauth, secret, is_member
        self._secure_cookies = secure_cookies

    # ------------------------------------------------------------ connexion

    def _set_cookie(self, response: web.StreamResponse, name: str, payload: dict[str, Any], max_age: int) -> None:
        response.set_cookie(
            name, sign(payload, self._secret), max_age=max_age, path="/", httponly=True,
            secure=self._secure_cookies, samesite="Lax",
        )

    @staticmethod
    def _redirect(location: str) -> web.Response:
        return web.Response(status=302, headers={"Location": location})

    def _set_session(self, response: web.StreamResponse, user: dict[str, Any]) -> None:
        self._set_cookie(response, SESSION_COOKIE, user, SESSION_SECONDS)

    @web.middleware
    async def _auth_middleware(self, request: web.Request, handler):
        if self.oauth is None:
            return await handler(request)

        user = unsign(request.cookies.get(SESSION_COOKIE), self._secret)
        refresh = clear = False
        guest = bool(user and user.get("guest"))
        if guest and not self._guest_ok(user):
            user, guest, clear = None, False, True  # accès invité retiré ou mot de passe changé
        if user is not None and not guest and time.time() - user.get("chk", 0) > MEMBER_RECHECK_SECONDS:
            # Revérification quotidienne : parti ou exclu du serveur → plus d'accès.
            member = await self._is_member(int(user["id"])) if self._is_member else None
            if member is False:
                user, clear = None, True
            elif member is True:
                user["chk"] = int(time.time())
                refresh = True

        if guest:
            user = {**user, "id": self._guest_user_id()}
        viewer = Viewer(user, request.path_qs, guest=guest)
        if user is not None and int(user["id"]):
            viewer.characters = self.db.get_characters(int(user["id"]))
            is_admin = getattr(self.actions, "is_admin", None)
            if is_admin is not None:
                try:
                    viewer.admin = bool(await is_admin(int(user["id"])))
                except Exception:
                    log.exception("Vérification des droits d'administration impossible")
        token = _VIEWER.set(viewer)
        try:
            if user is None and not request.path.startswith(PUBLIC_PATHS):
                response: web.StreamResponse = self._login_page(request.path_qs)
            elif guest and request.method not in ("GET", "HEAD") and not request.path.startswith("/auth/"):
                response = self._message_page(
                    "Lecture seule", "L'accès invité permet de consulter le site, pas d'y faire des actions.", 403
                )
            else:
                response = await handler(request)
        finally:
            _VIEWER.reset(token)
        if refresh and user is not None:
            self._set_session(response, user)
        if clear:
            response.del_cookie(SESSION_COOKIE, path="/")
        return response

    def _login_page(self, next_path: str) -> web.Response:
        body = f"""<div class="login-box card">
<h1 class="title">Réservé aux membres</h1>
<p class="sub">Les persos, métiers et recettes du serveur sont visibles par les membres du Discord.
Connecte-toi avec ton compte Discord : le site ne voit que ton pseudo.</p>
<p><a class="btn" href="{esc(login_url(next_path))}">Se connecter avec Discord</a></p>
<p class="muted">Les <a href="/donjons">donjons et raids</a> restent consultables sans compte.
Première visite ? <a href="/aide#debut-connexion">Comment se connecter</a>.</p></div>"""
        response = page("Connexion", "", body)
        response.set_status(401)
        return response

    def _message_page(self, title: str, text: str, status: int) -> web.Response:
        body = (
            f'<div class="login-box card"><h1 class="title">{esc(title)}</h1><p class="sub">{text}</p>'
            '<p><a href="/donjons">Voir les donjons et raids</a></p></div>'
        )
        response = page(title, "", body)
        response.set_status(status)
        return response

    async def auth_login(self, request: web.Request) -> web.StreamResponse:
        if self.oauth is None:
            return self._redirect("/")
        state = secrets.token_urlsafe(24)
        response = self._redirect(self.oauth.authorize_url(state))
        payload = {"state": state, "next": safe_next(request.query.get("next")), "exp": time.time() + STATE_SECONDS}
        self._set_cookie(response, STATE_COOKIE, payload, STATE_SECONDS)
        return response

    async def auth_callback(self, request: web.Request) -> web.StreamResponse:
        if self.oauth is None:
            return self._redirect("/")
        pending = unsign(request.cookies.get(STATE_COOKIE), self._secret)
        state, code = request.query.get("state", ""), request.query.get("code")
        expected = str(pending.get("state", "")) if pending else ""
        if not expected or not code or not secrets.compare_digest(state.encode(), expected.encode()):
            # Refus sur Discord, lien trop vieux ou rejoué : on repart de zéro.
            return self._message_page(
                "Connexion annulée", f'La connexion n\'a pas abouti. <a href="{esc(login_url("/"))}">Réessayer</a>', 400
            )
        try:
            identity = await self.oauth.fetch_user(code)
        except OAuthError as exc:
            log.warning("Connexion Discord : %s", exc)
            return self._message_page(
                "Connexion impossible", "Discord n'a pas pu confirmer ton identité. Réessaie dans un moment.", 502
            )
        member = await self._is_member(identity["id"]) if self._is_member else None
        if member is not True:
            text = (
                "Ce site est réservé aux membres du serveur Discord."
                if member is False else "Impossible de vérifier ton appartenance au serveur pour l'instant. Réessaie plus tard."
            )
            response = self._message_page("Accès refusé" if member is False else "Vérification impossible", text, 403)
        else:
            response = self._redirect(safe_next(str(pending.get("next"))))
            now = int(time.time())
            self._set_session(response, {**identity, "chk": now, "exp": now + SESSION_SECONDS})
            log.info("Connexion au site : %s", identity["name"])
        response.del_cookie(STATE_COOKIE, path="/")
        return response

    def _guest_page(self, error: str = "", status: int = 200) -> web.Response:
        err = f'<p class="flash err" role="alert">{esc(error)}</p>' if error else ""
        body = f"""<div class="login-box card">
<h1 class="title">Accès invité</h1>
<p class="sub">Consultation du site sans compte Discord (lecture seule).</p>{err}
<form method="post" class="filters"><input type="password" name="password" placeholder="Mot de passe"
 autocomplete="current-password" required autofocus aria-label="Mot de passe">
<button class="btn" type="submit">Entrer</button></form></div>"""
        response = page("Accès invité", "", body)
        response.set_status(status)
        return response

    def _guest_key_ok(self, request: web.Request) -> bool:
        key = request.match_info.get("key", "")
        return bool(self._guest_key and self._guest_password and self.oauth is not None) and secrets.compare_digest(
            key.encode(), self._guest_key.encode()
        )

    async def guest_form(self, request: web.Request) -> web.StreamResponse:
        if not self._guest_key_ok(request):
            raise web.HTTPNotFound()  # le lien n'existe pas pour qui n'a pas la clé
        return self._guest_page()

    async def guest_login(self, request: web.Request) -> web.StreamResponse:
        if not self._guest_key_ok(request):
            raise web.HTTPNotFound()
        origin = request.headers.get("Origin")
        if origin and urlparse(origin).netloc != request.host:
            return self._guest_page("Formulaire envoyé depuis un autre site.", 403)
        now = time.monotonic()
        while self._guest_failures and now - self._guest_failures[0] > GUEST_FAIL_WINDOW:
            self._guest_failures.popleft()
        if len(self._guest_failures) >= GUEST_MAX_FAILURES:
            return self._guest_page("Trop d'essais ratés, réessaie dans quelques minutes.", 429)
        password = str((await request.post()).get("password", ""))
        ok = secrets.compare_digest(
            hashlib.sha256(password.encode()).digest(), hashlib.sha256(self._guest_password.encode()).digest()
        )
        if not ok:
            self._guest_failures.append(now)
            log.warning("Accès invité : mot de passe incorrect")
            await asyncio.sleep(1)
            return self._guest_page("Mot de passe incorrect.", 401)
        response = self._redirect("/")
        stamp = int(time.time())
        self._set_session(response, {
            "id": 0, "name": "Invité", "guest": True, "g": self._guest_print(), "chk": stamp, "exp": stamp + SESSION_SECONDS,
        })
        log.info("Connexion au site : invité")
        return response

    async def auth_logout(self, request: web.Request) -> web.StreamResponse:
        response = self._redirect("/donjons")
        response.del_cookie(SESSION_COOKIE, path="/")
        return response

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

    # ------------------------------------------------------------ serveur

    def app(self) -> web.Application:
        app = web.Application(middlewares=[self._auth_middleware])
        # Une seule instance pour toutes les pages des membres (ProfitPages hérite d'AuctionPages et de MemberPages) :
        # un seul état partagé (limite de vérifications dans l'armurerie, etc.).
        pages = ProfitPages(self)
        pages.register(app.router)
        pages.register_auction(app.router)
        pages.register_profit(app.router)
        AddonPages(self, pages).register(app.router)
        app.router.add_get("/auth/login", self.auth_login)
        app.router.add_get("/auth/callback", self.auth_callback)
        app.router.add_get("/auth/logout", self.auth_logout)
        app.router.add_get("/auth/invite/{key}", self.guest_form)
        app.router.add_post("/auth/invite/{key}", self.guest_login)
        GuildPages(self).register(app.router)
        HelpPages(self).register(app.router)
        LegalPages(self).register(app.router)
        app.router.add_get("/static/site.css", self.stylesheet)
        app.router.add_get("/static/logo.svg", self.logo)
        app.router.add_get("/favicon.ico", self.logo)
        return app

    async def stylesheet(self, request: web.Request) -> web.Response:
        """Feuille de style, gardée un an par le navigateur (son adresse change à chaque version du site)."""
        return web.Response(
            text=STYLESHEET, content_type="text/css", headers={"Cache-Control": "public, max-age=31536000, immutable"}
        )

    async def logo(self, request: web.Request) -> web.Response:
        """Logo du site (créé par ideapub), aussi servi comme favicon."""
        return web.Response(body=LOGO, content_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})

    async def start(self, host: str, port: int) -> None:
        self._runner = web.AppRunner(self.app(), access_log=None)
        await self._runner.setup()
        await web.TCPSite(self._runner, host, port).start()
        log.info("Site web démarré sur %s:%d", host, port)

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
