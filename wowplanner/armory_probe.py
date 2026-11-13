"""Test de l'API armurerie de WoW Forever, sans lancer le bot.

    python -m wowplanner.armory_probe "Grommash Hurlenfer" ["Autre Perso" ...] [--region eu]

Dans Docker, sur le VPS :

    docker compose run --rm wowplanner python -m wowplanner.armory_probe "Grommash Hurlenfer"

Lit BLIZZARD_CLIENT_ID / BLIZZARD_CLIENT_SECRET (et BLIZZARD_REGION) dans le .env.
Affiche ce qui répond, et enregistre chaque réponse brute en JSON dans
DATA_DIR/armory_probe/ pour qu'on voie le vrai format des données.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import aiohttp
from dotenv import load_dotenv

from .armory import CHARACTER_ENDPOINTS, ArmoryClient, ArmoryError, character_slug

# Données de jeu (pas de perso) : vérifient que les identifiants et les espaces de noms marchent.
GAME_DATA_CHECKS = (
    ("/data/wow/region/index", "dynamic-forever"),
    ("/data/wow/ruleset/index", "dynamic-forever"),
    ("/data/wow/playable-class/index", "static-forever"),
)


def _name(obj: Any) -> str:
    """Les noms localisés arrivent en texte (avec locale) ou en dict {fr_FR: …}."""
    if isinstance(obj, dict):
        return str(obj.get("name") or next(iter(obj.values()), "?"))
    return str(obj)


def summarize(endpoint: str, data: dict[str, Any]) -> list[str]:
    """Quelques lignes lisibles par sous-ressource ; le reste est dans le JSON."""
    if endpoint == "":
        return [
            f"nom : {data.get('name')} {data.get('surname', '')}".rstrip(),
            f"niveau {data.get('level')} · {_name(data.get('race', {}))} {_name(data.get('character_class', {}))}",
            f"guilde : {_name(data.get('guild', {})) if data.get('guild') else '—'}",
            f"item level moyen / équipé : {data.get('average_item_level')} / {data.get('equipped_item_level')}",
            f"clés : {', '.join(sorted(data))}",
        ]
    if endpoint == "/statistics":
        keys = ("health", "power", "strength", "agility", "intellect", "stamina", "armor", "melee_crit", "spell_crit")
        lines = []
        for k in keys:
            v = data.get(k)
            if isinstance(v, dict):
                v = v.get("effective", v.get("value", v))
            if v is not None:
                lines.append(f"{k} : {v}")
        return lines + [f"clés : {', '.join(sorted(data))}"]
    if endpoint == "/equipment":
        items = data.get("equipped_items", [])
        return [f"{len(items)} pièces"] + [
            f"{_name(i.get('slot', {}))} : {_name(i)} (ilvl {i.get('level', {}).get('value', '?')})" for i in items[:20]
        ]
    if endpoint == "/professions":
        lines = []
        for kind in ("primaries", "secondaries"):
            for p in data.get(kind, []):
                tiers = p.get("tiers") or []
                skill = p.get("skill_points") or (tiers[0].get("skill_points") if tiers else None)
                maxi = p.get("max_skill_points") or (tiers[0].get("max_skill_points") if tiers else None)
                lines.append(f"{kind} : {_name(p.get('profession', {}))} {skill}/{maxi} ({len(tiers)} palier(s))")
        return lines or [f"aucun métier — clés : {', '.join(sorted(data))}"]
    if endpoint == "/specializations":
        return [f"clés : {', '.join(sorted(data))}"]
    if endpoint == "/character-media":
        return [f"{a.get('key')} : {a.get('value')}" for a in data.get("assets", [])]
    return [f"clés : {', '.join(sorted(data))}"]


async def probe(names: list[str], region: str, out_dir: Path) -> int:
    client_id = os.getenv("BLIZZARD_CLIENT_ID", "").strip()
    client_secret = os.getenv("BLIZZARD_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        print("❌ BLIZZARD_CLIENT_ID et BLIZZARD_CLIENT_SECRET manquants dans le .env "
              "(à créer sur https://develop.battle.net → Create Client).")
        return 2

    out_dir.mkdir(parents=True, exist_ok=True)
    ok = 0
    async with aiohttp.ClientSession(headers={"User-Agent": "wowplanner-armory-probe"}) as session:
        api = ArmoryClient(session, client_id, client_secret, region)

        print(f"== Jeton ({region.upper()})")
        try:
            await api.get_token()
            print("✅ jeton obtenu")
        except (ArmoryError, aiohttp.ClientError) as exc:
            print(f"❌ {exc}")
            return 1

        print("\n== Données de jeu")
        for path, ns in GAME_DATA_CHECKS:
            try:
                data = await api.get(path, ns)
                print(f"✅ {path} ({ns}) : {', '.join(sorted(data))[:120]}")
            except (ArmoryError, aiohttp.ClientError) as exc:
                print(f"❌ {path} ({ns}) : {exc}")

        for name in names:
            slug = character_slug(name)
            print(f"\n== {name} → {slug}")
            for endpoint in CHARACTER_ENDPOINTS:
                label = endpoint or "/ (fiche)"
                try:
                    data = await api.character(name, endpoint)
                except (ArmoryError, aiohttp.ClientError) as exc:
                    print(f"❌ {label} : {exc}")
                    continue
                ok += 1
                file = out_dir / f"{slug}{endpoint.replace('/', '_') or '_profile'}.json"
                file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"✅ {label}  → {file}")
                for line in summarize(endpoint, data):
                    print(f"     {line}")

    print(f"\n{ok} réponse(s) OK. Fichiers JSON dans {out_dir}")
    return 0 if ok else 1


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Teste l'API armurerie de WoW Forever.")
    parser.add_argument("persos", nargs="+", help='Nom complet du perso, ex. "Grommash Hurlenfer"')
    parser.add_argument("--region", default=os.getenv("BLIZZARD_REGION", "eu"), help="eu, us, kr, tw (défaut : eu)")
    parser.add_argument(
        "--out", type=Path, default=Path(os.getenv("DATA_DIR", "data")) / "armory_probe",
        help="Dossier des réponses JSON",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(probe(args.persos, args.region, args.out)))


if __name__ == "__main__":
    main()
