"""Site de démonstration pour les captures de la page d'aide : la base de demo_build.py, un faux bot, et une
connexion automatique (/auth/demo) en tant que « Elwyn », administrateur. Ne jamais le lancer en production.

Usage (depuis la racine du dépôt) : python tools/aide/demo_server.py demo.db [port]
"""
import asyncio
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from wowplanner.db import Database  # noqa: E402
from wowplanner.orders import orderable  # noqa: E402
from wowplanner.recipes import crafted_by_map  # noqa: E402
from wowplanner.web import WebSite  # noqa: E402
from wowplanner.webauth import SESSION_COOKIE, SESSION_SECONDS, DiscordOAuth, sign  # noqa: E402

DB = Path(sys.argv[1])
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8766
GUILD, ME = 42, 1
NAMES = {1: "Elwyn", 2: "Grom", 3: "Feuille", 4: "Gwoo", 5: "Aelys", 6: "Brindille", 7: "Mirielle"}


class Backend:
    timezone = ZoneInfo("Europe/Paris")
    armory_enabled = True
    sync_state = None

    def __init__(self, db):
        self.db = db

    async def is_admin(self, user_id):
        return user_id == ME

    def last_sync(self):
        return time.time() - 5 * 3600

    async def member_names(self, ids):
        return {i: NAMES.get(i, f"Membre{i}") for i in ids}

    def match_instance(self, *names):
        return None

    def event_channels(self):
        return [(7, "#sorties")]

    def instance_options(self):
        return [("Les Mortemines", "Les Mortemines — Donjon 5 joueurs (17-26)"),
                ("Donjon de Forgebraise", "Donjon de Forgebraise — Donjon 5 joueurs (22-30)"),
                ("Profondeurs des tertres", "Profondeurs des tertres — Raid 10 joueurs (60)")]

    async def can_manage(self, user_id, ev):
        return user_id == ev.creator_id

    def orderable(self, user_id):
        return orderable(self.db.guild_recipes(GUILD), self.db.recipe_crafters(GUILD), user_id)

    def user_orders(self, user_id):
        return self.db.user_orders(user_id, closed_limit=10)

    def crafted_by(self):
        return crafted_by_map(self.db.guild_recipes(GUILD))

    async def armory_lookup(self, user_id, name):
        return {"status": "found", "name": name, "level": 30, "class": "Mage", "race": "Gnome"}


async def main():
    db = Database(DB)
    site = WebSite(db, lambda: GUILD)
    secret = b"d" * 32

    async def is_member(user_id):
        return True

    site.enable_auth(DiscordOAuth(None, "1", "s", "http://localhost/auth/callback"), secret, is_member, secure_cookies=False)
    site.enable_actions(Backend(db))
    site.auction_house = 111
    app = site.app()

    async def demo_login(request):
        now = int(time.time())
        resp = web.Response(status=302, headers={"Location": request.query.get("next", "/")})
        resp.set_cookie(SESSION_COOKIE, sign({"id": ME, "name": "Elwyn", "chk": now, "exp": now + SESSION_SECONDS}, secret),
                        path="/", httponly=True)
        return resp

    app.router.add_get("/auth/demo", demo_login)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", PORT).start()
    print(f"Démo prête : http://127.0.0.1:{PORT}/auth/demo", flush=True)
    await asyncio.Event().wait()


asyncio.run(main())
