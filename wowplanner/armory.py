"""Client de l'API Blizzard pour l'armurerie de WoW Forever.

Rien n'est documenté officiellement pour Forever (novembre 2026). D'après les tests de la
communauté :
- espaces de noms `profile-forever-{region}` (persos), `dynamic-forever-{region}`,
  `static-forever-{region}` ;
- pas de serveur dans l'adresse : un perso s'adresse par `prénom-nom` en minuscules,
  ex. /profile/wow/character/grommash-hurlenfer?namespace=profile-forever-eu ;
- un perso n'apparaît qu'à partir du niveau 10, après une déconnexion, parfois avec
  plusieurs heures de retard ;
- jeton « client credentials » (application) suffisant pour les données publiques.

Tout peut changer sans préavis : les appelants doivent supporter les erreurs (ArmoryError).
"""
from __future__ import annotations

import asyncio
import base64
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import aiohttp

from .gamedata import BLIZZARD_CLASS_IDS, BLIZZARD_PROFESSION_IDS, BLIZZARD_RACE_IDS

TOKEN_URL = "https://oauth.battle.net/token"
# Les données d'un perso changent à sa déconnexion : inutile de les redemander à chaque commande.
CACHE_SECONDS = 600
LOCALES = {"eu": "fr_FR", "us": "en_US", "kr": "ko_KR", "tw": "zh_TW"}

# Sous-ressources d'un perso testées par la communauté (« » = la fiche elle-même).
CHARACTER_ENDPOINTS = (
    "",
    "/statistics",
    "/equipment",
    "/professions",
    "/specializations",
    "/character-media",
)


class ArmoryError(Exception):
    def __init__(self, status: int, url: str, detail: str = ""):
        self.status = status
        self.url = url
        super().__init__(f"HTTP {status} sur {url}" + (f" : {detail}" if detail else ""))


def character_slug(name: str) -> str:
    """« Grommash Hurlenfer » → « grommash-hurlenfer » (forme des adresses de l'armurerie)."""
    return "-".join(name.strip().lower().split())


@dataclass
class ArmoryClient:
    session: aiohttp.ClientSession
    client_id: str
    client_secret: str
    region: str = "eu"
    timeout: float = 15
    # Modifiables pour les tests (faux serveur local).
    base_url: str = ""
    token_url: str = TOKEN_URL

    def __post_init__(self) -> None:
        self.region = self.region.lower()
        self.locale = LOCALES.get(self.region, "en_US")
        self.base_url = self.base_url or f"https://{self.region}.api.blizzard.com"
        self._token: str | None = None
        self._cache: dict[str, tuple[float, ArmorySheet]] = {}
        self._token_expires = 0.0

    # ------------------------------------------------------------------ jeton

    async def get_token(self) -> str:
        """Jeton d'application (client credentials), réutilisé jusqu'à une minute avant expiration."""
        if self._token and time.monotonic() < self._token_expires - 60:
            return self._token
        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        async with self.session.post(
            self.token_url,
            data={"grant_type": "client_credentials"},
            headers={"Authorization": f"Basic {basic}"},
            timeout=aiohttp.ClientTimeout(total=self.timeout),
        ) as resp:
            if resp.status != 200:
                raise ArmoryError(resp.status, self.token_url, "identifiants Blizzard refusés ?")
            payload = await resp.json()
        self._token = payload["access_token"]
        self._token_expires = time.monotonic() + float(payload.get("expires_in", 3600))
        return self._token

    # ---------------------------------------------------------------- requêtes

    async def get(self, path: str, namespace: str) -> dict[str, Any]:
        """GET brut sur l'API. `namespace` sans la région, ex. « profile-forever »."""
        token = await self.get_token()
        url = f"{self.base_url}{path}"
        params = {"namespace": f"{namespace}-{self.region}", "locale": self.locale}
        async with self.session.get(
            url,
            params=params,
            headers={"Authorization": f"Bearer {token}"},
            timeout=aiohttp.ClientTimeout(total=self.timeout),
        ) as resp:
            if resp.status != 200:
                detail = (await resp.text())[:200]
                raise ArmoryError(resp.status, f"{url}?namespace={params['namespace']}", detail)
            return await resp.json()

    async def character(self, name: str, endpoint: str = "") -> dict[str, Any]:
        """Fiche d'un perso (endpoint vide) ou une sous-ressource : « /statistics », « /professions »…"""
        slug = quote(character_slug(name))
        return await self.get(f"/profile/wow/character/{slug}{endpoint}", "profile-forever")

    async def recipe(self, recipe_id: int) -> dict[str, Any]:
        """Détail d'une recette (nom localisé, composants). Donnée statique : à mettre en cache."""
        return await self.get(f"/data/wow/recipe/{recipe_id}", "static-forever")

    # ------------------------------------------------------------ fiche complète

    async def sheet(self, name: str, max_age: float = CACHE_SECONDS) -> ArmorySheet:
        """Fiche + stats, équipement, métiers, spé et image, en parallèle et avec cache.

        Lève ArmoryError si la fiche elle-même est introuvable (404 : perso < niv. 10, jamais
        déconnecté, ou faute de frappe). Les sous-ressources qui échouent valent None.
        """
        slug = character_slug(name)
        cached = self._cache.get(slug)
        if cached and time.monotonic() - cached[0] < max_age:
            return cached[1]

        async def part(endpoint: str) -> dict[str, Any] | None:
            try:
                return await self.character(name, endpoint)
            except (ArmoryError, aiohttp.ClientError, asyncio.TimeoutError):
                return None

        profile, statistics, equipment, professions, specializations, media = await asyncio.gather(
            self.character(name), part("/statistics"), part("/equipment"),
            part("/professions"), part("/specializations"), part("/character-media"),
        )
        result = ArmorySheet(profile, statistics, equipment, professions, specializations, media)
        self._cache[slug] = (time.monotonic(), result)
        return result


@dataclass
class ArmorySheet:
    """Réponses brutes de l'armurerie pour un perso, avec des accesseurs pratiques."""

    profile: dict[str, Any]
    statistics: dict[str, Any] | None = None
    equipment: dict[str, Any] | None = None
    professions: dict[str, Any] | None = None
    specializations: dict[str, Any] | None = None
    media: dict[str, Any] | None = None

    @property
    def full_name(self) -> str:
        return " ".join(p for p in (self.profile.get("name"), self.profile.get("surname")) if p)

    @property
    def level(self) -> int | None:
        return self.profile.get("level")

    @property
    def class_key(self) -> str | None:
        return BLIZZARD_CLASS_IDS.get((self.profile.get("character_class") or {}).get("id"))

    @property
    def race_key(self) -> str | None:
        return BLIZZARD_RACE_IDS.get((self.profile.get("race") or {}).get("id"))

    def label(self, field: str) -> str | None:
        """Nom localisé d'un champ du profil (race, character_class, faction…)."""
        value = self.profile.get(field)
        return value.get("name") if isinstance(value, dict) else None

    @property
    def active_spec(self) -> tuple[str, int] | None:
        """(nom, points) de l'arbre le plus investi dans le groupe de talents actif."""
        for group in (self.specializations or {}).get("specialization_groups", []):
            if not group.get("is_active"):
                continue
            specs = [
                (s.get("specialization", {}).get("name") or s.get("specialization_name"), s.get("spent_points") or 0)
                for s in group.get("specializations", [])
            ]
            specs = [s for s in specs if s[0]]
            if specs:
                return max(specs, key=lambda s: s[1])
        return None

    def asset(self, key: str) -> str | None:
        """URL d'une image : « avatar », « main-raw »…"""
        return next((a.get("value") for a in (self.media or {}).get("assets", []) if a.get("key") == key), None)

    def profession_skills(self) -> dict[str, tuple[int | None, int | None]] | None:
        """{clé métier : (niveau, plafond actuel)}. None si les métiers n'ont pas pu être lus."""
        if self.professions is None:
            return None
        skills: dict[str, tuple[int | None, int | None]] = {}
        for kind in ("primaries", "secondaries"):
            for p in self.professions.get(kind, []):
                key = BLIZZARD_PROFESSION_IDS.get((p.get("profession") or {}).get("id"))
                if key is None:
                    continue
                tiers = p.get("tiers") or [{}]
                skill = p.get("skill_points", tiers[0].get("skill_points"))
                maxi = p.get("max_skill_points", tiers[0].get("max_skill_points"))
                skills[key] = (skill, maxi)
        return skills

    def known_recipes(self) -> dict[str, list[tuple[int, str]]] | None:
        """{clé métier : [(id recette, nom anglais), …]}. None si les métiers n'ont pas pu être lus."""
        if self.professions is None:
            return None
        recipes: dict[str, list[tuple[int, str]]] = {}
        for kind in ("primaries", "secondaries"):
            for p in self.professions.get(kind, []):
                key = BLIZZARD_PROFESSION_IDS.get((p.get("profession") or {}).get("id"))
                if key is None:
                    continue
                for tier in p.get("tiers") or []:
                    for r in tier.get("known_recipes") or []:
                        if isinstance(r.get("id"), int):
                            recipes.setdefault(key, []).append((r["id"], r.get("name") or f"#{r['id']}"))
        return recipes


@dataclass
class RecipeDetails:
    name: str
    reagents: list[tuple[int, str, int | None]]  # (quantité, composant, id de l'objet)
    crafted_item_id: int | None  # objet fabriqué (None : enchantement, etc.)
    crafted_quantity: float  # objets obtenus par fabrication


def parse_recipe(data: dict[str, Any]) -> RecipeDetails:
    """Détail d'une recette depuis /data/wow/recipe/{id}."""
    reagents = [
        (
            int(r.get("quantity") or 1),
            (r.get("reagent") or {}).get("name") or "?",
            (r.get("reagent") or {}).get("id"),
        )
        for r in data.get("reagents") or []
    ]
    crafted = data.get("crafted_item") or data.get("alliance_crafted_item") or data.get("horde_crafted_item") or {}
    quantity = (data.get("crafted_quantity") or {}).get("value") or 1
    return RecipeDetails(data.get("name") or "?", reagents, crafted.get("id"), float(quantity))
