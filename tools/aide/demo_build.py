"""Base de démonstration pour les captures de la page d'aide (voir README, « Page d'aide »).

Persos inventés (aucun joueur réel), sauf Hollie Tétine relue dans l'armurerie pour une fiche complète ;
pseudo Discord inventé (« Elwyn ») ; vraies recettes de couture et de forge (données de jeu Blizzard) ; prix
réels de l'hôtel des ventes avec un historique simulé ; sorties et commandes d'exemple.

Usage (depuis la racine du dépôt, clés Blizzard dans .env) : python tools/aide/demo_build.py demo.db
"""
import asyncio
import math
import os
import random
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import aiohttp
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
load_dotenv(".env")

from wowplanner.auctions import PricePoint  # noqa: E402
from wowplanner.cogs.armory import ArmoryCog  # noqa: E402
from wowplanner.cogs.auctions import AuctionCog  # noqa: E402
from wowplanner.db import Database, Event, Order  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "demo.db")
GUILD = 42
ME = 1  # le visiteur connecté de la démo (« Elwyn »), propriétaire de Hollie
HOUSE = 111
PSEUDO = "Elwyn"
TZ = ZoneInfo("Europe/Paris")

FAKES = [
    # (joueur, nom, classe, race, rôle, niveau, métiers)
    (2, "Grommash Hurlenfer", "guerrier", "humain", "tank", 60, {"forge": 285, "minage": 300}),
    (2, "Xfalsia Ombrelune", "demoniste", "gnome", None, 42, {"couture": 180, "enchantement": 150}),
    (3, "Feuille Dorée", "druide", "elfe_nuit", "heal", 27, {"herboristerie": 140, "alchimie": 125}),
    (4, "Gwoo Pique-Fer", "chasseur", "nain", "dps", 16, {"travail_cuir": 75, "depecage": 90, "cuisine": 60}),
    (5, "Aelys Lumière", "paladin", "humain", "tank", 38, {"ingenierie": 175, "minage": 190}),
    (6, "Brindille Sombreval", "voleur", "nain", "dps", 24, {"herboristerie": 110, "alchimie": 95}),
    (7, "Mirielle Clairsoleil", "mage", "gnome", "dps", 19, {"couture": 105, "enchantement": 90}),
]
# Recettes données aux persos inventés : (perso, id du métier Blizzard, id du palier, clé du métier).
CRAFTERS = [("Xfalsia Ombrelune", 197, 2948, "couture"), ("Grommash Hurlenfer", 164, 2938, "forge")]


async def main():
    if OUT.exists():
        OUT.unlink()
    db = Database(OUT)
    hollie = db.add_character(ME, "Hollie Tétine", "pretre", "humain", "heal")
    db.set_favorite(ME, hollie.id)
    chars = {}
    for user_id, name, cls, race, role, level, profs in FAKES:
        c = db.add_character(user_id, name, cls, race, role)
        db.replace_professions(c.id, profs)
        db.set_armory_look(c.id, level, None, None)
        chars[name] = c
    for user_id in range(1, 8):
        db.touch_member(GUILD, user_id)

    async with aiohttp.ClientSession() as session:
        cfg = SimpleNamespace(
            blizzard_client_id=os.environ["BLIZZARD_CLIENT_ID"],
            blizzard_client_secret=os.environ["BLIZZARD_CLIENT_SECRET"],
            blizzard_region=os.getenv("BLIZZARD_REGION", "eu"), auction_house_id=HOUSE, auction_ruleset=1,
        )
        cogs = {}
        bot = SimpleNamespace(db=db, config=cfg, http_session=session, get_cog=lambda n: cogs.get(n))
        armory = ArmoryCog(bot)
        await armory.cog_load()
        cogs["ArmoryCog"] = armory
        await armory.fetch_talent_trees()
        print("Hollie :", "trouvée" if (await armory.sync(hollie)).found else "introuvable")
        for who, profession, tier, key in CRAFTERS:
            data = await armory.client.get(f"/data/wow/profession/{profession}/skill-tier/{tier}", "static-forever")
            picked = [(r["id"], r["name"]) for cat in data["categories"] for r in cat["recipes"][:10]]
            db.replace_character_recipes(chars[who].id, {key: picked})
        print("recettes :", await armory.fetch_recipe_details(db.recipes_missing_details()))
        print("HdV :", await AuctionCog(bot).refresh())

    # Historique simulé : 30 jours d'oscillations autour du prix actuel (les courbes ont de quoi montrer).
    now = int(time.time()) // 3600 * 3600
    latest = db.conn.execute("SELECT * FROM ah_latest").fetchall()
    rng = random.Random(7)
    for hours_ago in list(range(1, 24 * 7)) + list(range(24 * 7, 24 * 30, 24)):
        ts = now - hours_ago * 3600
        rows = []
        for r in latest:
            wave = 1 + 0.18 * math.sin(hours_ago / 19 + r["item_id"] % 7) + rng.uniform(-0.08, 0.08)
            p = PricePoint(max(1, int(r["min_price"] * wave)), max(1, int(r["median_price"] * wave)),
                           max(1, int(r["quantity"] * rng.uniform(0.6, 1.3))), r["listings"])
            rows.append((r["item_id"], ts, p.min_price, p.median_price, p.quantity, p.listings))
        db.conn.executemany("INSERT OR REPLACE INTO ah_prices VALUES (?, ?, ?, ?, ?, ?)", rows)
    db.conn.commit()

    for name in ("Étoffe de lin", "Étoffe de laine", "Minerai de cuivre", "Pacifique", "Feuillargent", "Peau légère"):
        row = db.conn.execute("SELECT id FROM ah_items WHERE name = ?", (name,)).fetchone()
        if row:
            db.toggle_ah_favorite(ME, row["id"])

    # Sorties, à heures rondes.
    base = datetime.now(TZ).replace(minute=0, second=0, microsecond=0)
    at = lambda days, hour: int((base + timedelta(days=days)).replace(hour=hour).timestamp())  # noqa: E731
    for ev in (
        Event(1001, GUILD, 7, 2, "Les Mortemines", "dungeon", "17-26", at(1, 21), {"tank": 1, "heal": 1, "dps": 3},
              description="RDV devant l'entrée à Ruisselune. Pensez aux potions !", creator_name="Grom"),
        Event(1002, GUILD, 7, ME, "Donjon de Forgebraise", "dungeon", "22-30", at(2, 20), {"tank": 1, "heal": 1, "dps": 3},
              creator_name=PSEUDO),
        Event(1003, GUILD, 7, 5, "Profondeurs des tertres", "raid", "60", at(6, 21), {"tank": 2, "heal": 3, "dps": 5},
              description="Premier essai du raid, stuff bleu conseillé.", creator_name="Aelys"),
    ):
        db.create_event(ev)
    for mid, uid, role, display, name in (
        (1001, 2, "tank", "Grom", "Grommash Hurlenfer"), (1001, 4, "dps", "Gwoo", "Gwoo Pique-Fer"),
        (1001, 6, "dps", "Brindille", "Brindille Sombreval"), (1002, ME, "heal", PSEUDO, None),
        (1002, 5, "tank", "Aelys", "Aelys Lumière"), (1002, 3, "dps", "Feuille", "Feuille Dorée"),
        (1003, 5, "tank", "Aelys", "Aelys Lumière"), (1003, 2, "dps", "Grom", "Grommash Hurlenfer"),
    ):
        db.upsert_signup(mid, uid, role, display, chars[name].id if name else hollie.id)

    # Commandes : une reçue (à Hollie), une passée (à Xfalsia).
    known = db.character_recipe_ids(hollie.id)
    mine = [r for r in db.guild_recipes(GUILD) if r.id in known]
    theirs = [r for r in db.guild_recipes(GUILD, "couture") if r.id not in known]
    if mine:
        db.create_order(Order(GUILD, 4, "Gwoo", mine[0].id, mine[0].name, 2, hollie.id, "Hollie Tétine", ME,
                              reagents_text="Composants selon la recette", note="Je t'envoie l'étoffe par courrier ce soir !"))
    if theirs:
        x = chars["Xfalsia Ombrelune"]
        db.create_order(Order(GUILD, ME, PSEUDO, theirs[3].id, theirs[3].name, 1, x.id, x.name, 2, status="accepted",
                              reagents_text="Composants selon la recette"))
    db.close()
    print("Base de démo prête :", OUT)


asyncio.run(main())
