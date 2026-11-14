"""Priorités de stats par spé, relues chaque nuit sur le guide WoW Forever de stillsixty.com.

La page contient des tableaux « spé → liste de stats » (ex. « Shadow Priest » → « Hit, Spell Power,
Critical Strike, … ») et les caps de toucher (« Spells » → « 16%, which is 160 Hit Rating »). On les
traduit en jetons de gear.TOKENS. Si la page change de forme, on garde les dernières priorités connues
(ou celles écrites dans gear.py) : rien n'est remplacé par une lecture douteuse.
"""
from __future__ import annotations

import html
import re

import aiohttp

SOURCE_URL = "https://www.stillsixty.com/guides/stats-and-attributes"
# Le site refuse les clients sans en-tête de navigateur (502) : en-tête générique, sans info sur nous.
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
                         " Chrome/130.0 Safari/537.36"}
# En dessous, on considère que la page a changé de forme et on ne touche à rien.
MIN_SPECS = 25

# Intitulés de lignes du guide → clé de gear.PRIORITIES.
SPEC_NAMES = {
    "balance druid": "balance", "feral druid, cat": "feral_cat", "feral druid, bear": "feral_bear",
    "restoration druid": "resto_druid", "holy paladin": "holy_paladin", "protection paladin": "prot_paladin",
    "retribution paladin": "ret", "assassination rogue": "assassination", "combat rogue": "combat",
    "subtlety rogue": "subtlety", "arcane mage": "arcane", "fire mage": "fire", "frost mage": "frost",
    "discipline priest": "discipline", "holy priest": "holy_priest", "shadow priest": "shadow",
    "affliction warlock": "affliction", "demonology warlock": "demonology", "destruction warlock": "destruction",
    "arms warrior": "arms", "fury warrior, dual wield": "fury", "fury warrior, two-hand": "fury_2h",
    "protection warrior": "prot_warrior", "beast mastery hunter": "beast_mastery",
    "marksmanship hunter": "marksmanship", "survival hunter": "survival", "elemental shaman": "elemental",
    "enhancement shaman": "enhancement", "enhancement shaman, dungeon tank": "enhancement_tank",
    "restoration shaman": "resto_shaman",
}

# Expressions du guide → jetons, les plus longues d'abord (certaines contiennent des virgules ou « and »).
PHRASES = (
    ("block chance and block value", "avoidance,block_value"),
    ("dodge, parry and block", "avoidance"),
    ("dodge and parry reduction", "expertise"),
    ("weapon damage per second", "weapon_dps"),
    ("mana per 5 seconds", "mp5"),
    ("critical strike", "crit"),
    ("healing power", "healing"),
    ("spell power", "spell_power"),
    ("attack power", "attack_power"),
    ("weapon skill", "weapon_skill"),
    ("block value", "block_value"),
    ("intellect", "intellect"), ("stamina", "stamina"), ("strength", "strength"), ("agility", "agility"),
    ("spirit", "spirit"), ("haste", "haste"), ("hit", "hit"), ("expertise", "expertise"),
    ("defense", "defense"), ("armor", "armor"),
)

_ROW = re.compile(r'<th scope="row"[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>', re.S)


def _text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def parse_tokens(text: str) -> list[str] | None:
    """« Hit, Spell Power, Critical Strike » → ["hit", "spell_power", "crit"] ; None si une stat est inconnue."""
    work = text.casefold()
    for phrase, tokens in PHRASES:
        work = re.sub(r"\b" + re.escape(phrase) + r"\b", tokens.replace(",", "|"), work)
    result: list[str] = []
    for part in work.split(","):
        for token in part.strip().rstrip(".").split("|"):
            token = token.strip()
            if not token:
                continue
            if not re.fullmatch(r"[a-z_0-9]+", token) or token not in {t for _, ts in PHRASES for t in ts.split(",")}:
                return None
            if token not in result:
                result.append(token)
    return result or None


def parse_page(page: str) -> tuple[dict[str, list[str]], dict[str, float]]:
    """({clé de spé : jetons}, {"spell": 16.0, "physical": 9.0}) lus dans la page du guide."""
    specs: dict[str, list[str]] = {}
    caps: dict[str, float] = {}
    for head, cell in _ROW.findall(page):
        name, value = _text(head).casefold(), _text(cell)
        if name in SPEC_NAMES:
            tokens = parse_tokens(value)
            if tokens:
                specs[SPEC_NAMES[name]] = tokens
        elif name in ("spells", "melee and ranged attacks"):
            m = re.match(r"(\d+(?:[.,]\d+)?)\s*%", value)
            if m:
                caps["spell" if name == "spells" else "physical"] = float(m.group(1).replace(",", "."))
    return specs, caps


async def fetch(session: aiohttp.ClientSession, timeout: float = 30) -> tuple[dict[str, list[str]], dict[str, float]]:
    """Lit le guide ; lève ValueError si la page ne ressemble plus à ce qu'on attend."""
    async with session.get(SOURCE_URL, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
        if resp.status != 200:
            raise ValueError(f"HTTP {resp.status} sur {SOURCE_URL}")
        page = await resp.text()
    specs, caps = parse_page(page)
    if len(specs) < MIN_SPECS:
        raise ValueError(f"{len(specs)} spé(s) seulement reconnue(s) sur {SOURCE_URL} : la page a changé de forme ?")
    return specs, caps
