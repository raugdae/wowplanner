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
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import aiohttp

from .gamedata import BLIZZARD_CLASS_IDS, BLIZZARD_PROFESSION_IDS, BLIZZARD_RACE_IDS

TOKEN_URL = "https://oauth.battle.net/token"
# Les données d'un perso changent à sa déconnexion : inutile de les redemander à chaque commande.
CACHE_SECONDS = 600
# Réponses 429 (plus de 100 requêtes/s) : on réessaie après une petite pause.
RATE_LIMIT_RETRIES = 3
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
        for attempt in range(RATE_LIMIT_RETRIES + 1):
            async with self.session.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {token}"},
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as resp:
                if resp.status == 429 and attempt < RATE_LIMIT_RETRIES:
                    pass  # trop de requêtes : on souffle un peu et on réessaie
                elif resp.status != 200:
                    detail = (await resp.text())[:200]
                    raise ArmoryError(resp.status, f"{url}?namespace={params['namespace']}", detail)
                else:
                    return await resp.json()
            await asyncio.sleep(1 + attempt)
        raise AssertionError("unreachable")

    async def character(self, name: str, endpoint: str = "") -> dict[str, Any]:
        """Fiche d'un perso (endpoint vide) ou une sous-ressource : « /statistics », « /professions »…"""
        slug = quote(character_slug(name))
        return await self.get(f"/profile/wow/character/{slug}{endpoint}", "profile-forever")

    async def recipe(self, recipe_id: int) -> dict[str, Any]:
        """Détail d'une recette (nom localisé, composants). Donnée statique : à mettre en cache."""
        return await self.get(f"/data/wow/recipe/{recipe_id}", "static-forever")

    async def item(self, item_id: int) -> dict[str, Any]:
        """Objet (stats, effets…) depuis les données statiques de Forever."""
        return await self.get(f"/data/wow/item/{item_id}", "static-forever")

    async def talent_tree_index(self) -> dict[str, Any]:
        return await self.get("/data/wow/talent-tree/index", "static-forever")

    async def talent_tree(self, tree_id: int, spec_id: int) -> dict[str, Any]:
        """Arbre d'une spé : talents, positions dans la grille, rangs et descriptions."""
        return await self.get(f"/data/wow/talent-tree/{tree_id}/playable-specialization/{spec_id}", "static-forever")

    async def icon(self, kind: str, media_id: int) -> str | None:
        """Icône d'un sort (« spell ») ou d'une spé (« playable-specialization »), hébergée par Blizzard."""
        data = await self.get(f"/data/wow/media/{kind}/{media_id}", "static-forever")
        return icon_url(next((a.get("value") for a in data.get("assets", []) if a.get("key") == "icon"), None))

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

    @property
    def talents(self) -> list[dict[str, Any]] | None:
        """Talents choisis, par groupe (double spé) : [{"active", "specs": [{"spec_id", "name", "points",
        "talents": [[id talent, nom, rang, description], …]}]}]. None si la ressource n'a pas pu être lue."""
        if self.specializations is None:
            return None
        groups = []
        for group in self.specializations.get("specialization_groups") or []:
            specs = []
            for s in group.get("specializations") or []:
                spec = s.get("specialization") or {}
                talents = [
                    [
                        (t.get("talent") or {}).get("id"),
                        (t.get("talent") or {}).get("name") or (t.get("spell_tooltip") or {}).get("spell", {}).get("name"),
                        t.get("talent_rank") or 0,
                        (t.get("spell_tooltip") or {}).get("description"),
                    ]
                    for t in s.get("talents") or []
                ]
                specs.append({
                    "spec_id": spec.get("id"),
                    "name": spec.get("name") or s.get("specialization_name"),
                    "points": s.get("spent_points") or 0,
                    "talents": [t for t in talents if t[0]],
                })
            groups.append({"active": bool(group.get("is_active")), "specs": specs})
        return groups

    @property
    def avatar_url(self) -> str | None:
        return self.asset("avatar")

    @property
    def render_url(self) -> str | None:
        """Rendu du perso en pied, fond transparent."""
        return self.asset("main-raw") or self.asset("main")

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
    description: str | None = None  # effet de la recette (enchantements, qui ne créent pas d'objet)


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
    return RecipeDetails(
        data.get("name") or "?", reagents, crafted.get("id"), float(quantity), data.get("description") or None
    )


def icon_url(url: str | None) -> str | None:
    """Le CDN « forever » de Blizzard n'a pas toutes les icônes (403) ; celui du jeu principal les a toutes,
    avec les mêmes identifiants de fichier : …/forever-eu/icons/56/135463.jpg → …/eu/icons/56/135463.jpg."""
    return re.sub(r"/forever-([a-z]+)/icons/", r"/\1/icons/", url) if url else url


def parse_talent_index(data: dict[str, Any]) -> list[tuple[int, int]]:
    """(id d'arbre, id de spé) de chaque arbre, dans l'ordre du jeu, depuis /data/wow/talent-tree/index."""
    result = []
    for t in data.get("spec_talent_trees") or []:
        m = re.search(r"/talent-tree/(\d+)/playable-specialization/(\d+)", (t.get("key") or {}).get("href", ""))
        if m:
            result.append((int(m.group(1)), int(m.group(2))))
    return result


def parse_talent_tree(data: dict[str, Any]) -> dict[str, Any]:
    """Arbre d'une spé, réduit à ce qu'affiche le site. Gardé tel quel en base (JSON)."""
    nodes = []
    for n in data.get("spec_talent_nodes") or []:
        ranks = n.get("ranks") or []
        if not ranks:
            continue
        first = ranks[0].get("tooltip") or {}
        spell = first.get("spell_tooltip") or {}
        nodes.append({
            "id": n.get("id"),
            "talent": (first.get("talent") or {}).get("id"),
            "spell": (spell.get("spell") or {}).get("id"),
            "name": (first.get("talent") or {}).get("name") or (spell.get("spell") or {}).get("name") or "?",
            "row": n.get("display_row") or 1,
            "col": n.get("display_col") or 0,
            "max": len(ranks),
            "ranks": [((r.get("tooltip") or {}).get("spell_tooltip") or {}).get("description") or "" for r in ranks],
            "cast": spell.get("cast_time"),
            "cost": spell.get("power_cost"),
            "range": spell.get("range"),
            "cooldown": spell.get("cooldown"),
            "requires": [x for x in n.get("locked_by") or [] if isinstance(x, int)],
            "icon": None,
        })
    return {
        "tree_id": data.get("id"),
        "spec_id": (data.get("playable_specialization") or {}).get("id"),
        "name": data.get("name") or (data.get("playable_specialization") or {}).get("name") or "?",
        "class": BLIZZARD_CLASS_IDS.get((data.get("playable_class") or {}).get("id")),
        "icon": None,
        "nodes": nodes,
    }


def parse_item(data: dict[str, Any]) -> dict[str, Any]:
    """Infobulle d'un objet depuis /data/wow/item/{id} : {"quality": "RARE", "lines": [[genre, texte], …]}.

    Genres : type (emplacement · sous-type), bind, armor, weapon, stat, bag, effect (Utiliser / Équipé),
    flavor (texte d'ambiance), req (niveau requis). Gardé tel quel en base (JSON)."""
    p = data.get("preview_item") or data
    lines: list[list[str]] = []

    def add(kind: str, text: Any) -> None:
        if isinstance(text, str) and text.strip():
            lines.append([kind, text.strip()])

    slot = p.get("inventory_type") or {}
    slot_name = slot.get("name") if slot.get("type") not in (None, "NON_EQUIP") else None
    if slot_name:  # consommables : le type (« Élixirs », « Autre ») n'apprend rien
        add("type", " · ".join(x for x in (slot_name, (p.get("item_subclass") or {}).get("name")) if x))
    add("bind", (p.get("binding") or {}).get("name"))
    add("armor", ((p.get("armor") or {}).get("display") or {}).get("display_string"))
    weapon = p.get("weapon") or {}
    if weapon:
        parts = [
            (weapon.get("damage") or {}).get("display_string"),
            (weapon.get("attack_speed") or {}).get("display_string"),
            (weapon.get("dps") or {}).get("display_string"),
        ]
        add("weapon", " · ".join(x for x in parts if x))
    for stat in p.get("stats") or []:
        add("stat", (stat.get("display") or {}).get("display_string"))
    add("bag", (p.get("container_slots") or {}).get("display_string"))
    for spell in p.get("spells") or []:
        add("effect", spell.get("description"))
    add("flavor", p.get("description"))
    add("req", ((p.get("requirements") or {}).get("level") or {}).get("display_string"))
    item_class = data.get("item_class") or p.get("item_class") or {}
    subclass = data.get("item_subclass") or p.get("item_subclass") or {}
    return {
        "quality": (p.get("quality") or {}).get("type"), "lines": lines,
        # Pour classer les recettes : composants d'artisanat, consommables, armure par emplacement…
        "class": item_class.get("id"), "class_name": item_class.get("name"), "subclass_name": subclass.get("name"),
        "slot": slot.get("type"), "slot_name": slot.get("name"),
    }
