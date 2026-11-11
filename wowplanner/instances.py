"""Liste des donjons/raids de WoW Forever.

Source : le tableau « Dungeons and raids » de la page *World of Warcraft: Forever*
sur warcraft.wiki.gg, lu via l'API MediaWiki. Une copie est embarquée
(`instances_default.json`) pour que le bot fonctionne même si le wiki est injoignable ;
la dernière version téléchargée est mise en cache dans le dossier de données.
"""
from __future__ import annotations

import html
import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import aiohttp

log = logging.getLogger(__name__)

WIKI_API = "https://warcraft.wiki.gg/api.php"
WIKI_PAGE = "World of Warcraft: Forever"
WIKI_URL = "https://warcraft.wiki.gg/wiki/World_of_Warcraft:_Forever"
DEFAULT_PATH = Path(__file__).with_name("instances_default.json")

# Garde-fou : si le wiki change de structure, on garde l'ancienne liste plutôt qu'une liste vide.
MIN_DUNGEONS = 10
MIN_RAIDS = 1


@dataclass(frozen=True)
class Instance:
    name: str
    abbr: str
    kind: str  # "dungeon" | "raid"
    size: int
    location: str = ""
    levels: str | None = None
    new: bool = False

    @property
    def is_raid(self) -> bool:
        return self.kind == "raid"

    def short_label(self) -> str:
        if self.is_raid:
            return f"Raid {self.size} joueurs"
        return f"Donjon {self.size} joueurs" + (f" · niv. {self.levels}" if self.levels else "")

    def choice_label(self) -> str:
        abbr = f" ({self.abbr})" if self.abbr else ""
        return f"{self.name}{abbr} — {self.short_label()}"[:100]


# --------------------------------------------------------------------------- parsing wikitext

_LINK = re.compile(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]")
_TEXT_TEMPLATE = re.compile(r"\{\{\s*text\s*\|[^|}]*\|([^}]*)\}\}", re.I)
_TEMPLATE = re.compile(r"\{\{[^}]*\}\}")
_TAG = re.compile(r"<[^>]+>")
_TABLE = re.compile(r"\{\|(.*?)\n\s*\|\}", re.S)


def _clean(cell: str) -> str:
    s = _LINK.sub(r"\1", cell)
    s = _TEXT_TEMPLATE.sub(r"\1", s)
    s = _TEMPLATE.sub("", s)
    s = _TAG.sub("", s)
    s = s.replace("'''", "").replace("''", "")
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def parse_wikitext(text: str) -> list[Instance]:
    """Extrait les instances des tableaux dont la légende contient « dungeon » ou « raid »."""
    result: list[Instance] = []
    for table in _TABLE.findall(text):
        caption = ""
        headers: list[str] | None = None
        kind: str | None = None

        for raw in table.splitlines():
            line = raw.strip()
            if line.startswith("|+"):
                caption = _clean(line[2:]).lower()
                kind = "raid" if "raid" in caption else "dungeon" if "dungeon" in caption else None
            elif line.startswith("!"):
                headers = [_clean(h).lower() for h in re.split(r"!!|\|\|", line[1:])]
            elif line.startswith("|") and not line.startswith(("|-", "|}")):
                if kind is None or headers is None:
                    continue
                cells = [_clean(c) for c in line[1:].split("||")]
                inst = _row_to_instance(kind, headers, cells)
                if inst:
                    result.append(inst)
    return result


def _find(headers: list[str], cells: list[str], *prefixes: str) -> str:
    for i, h in enumerate(headers):
        if i < len(cells) and h.startswith(prefixes):
            return cells[i]
    return ""


def _row_to_instance(kind: str, headers: list[str], cells: list[str]) -> Instance | None:
    if not cells or not cells[0]:
        return None
    size_raw = _find(headers, cells, "limit", "size", "players", "joueurs")
    size_match = re.search(r"\d+", size_raw)
    size = int(size_match.group()) if size_match else (5 if kind == "dungeon" else 0)
    if size <= 0:
        return None
    levels = _find(headers, cells, "level") or None
    return Instance(
        name=cells[0],
        abbr=_find(headers, cells, "abbr"),
        kind=kind,
        size=size,
        location=_find(headers, cells, "location"),
        levels=levels.replace(" ", "") if levels else None,
        new=_find(headers, cells, "new").upper() == "NEW",
    )


async def fetch_from_wiki(session: aiohttp.ClientSession) -> list[Instance]:
    params = {
        "action": "parse",
        "page": WIKI_PAGE,
        "prop": "wikitext",
        "redirects": "1",
        "format": "json",
        "formatversion": "2",
    }
    timeout = aiohttp.ClientTimeout(total=30)
    async with session.get(WIKI_API, params=params, timeout=timeout) as resp:
        resp.raise_for_status()
        payload = await resp.json()
    if "error" in payload:
        raise RuntimeError(f"API du wiki : {payload['error'].get('info', payload['error'])}")
    instances = parse_wikitext(payload["parse"]["wikitext"])

    dungeons = sum(1 for i in instances if i.kind == "dungeon")
    raids = sum(1 for i in instances if i.kind == "raid")
    if dungeons < MIN_DUNGEONS or raids < MIN_RAIDS:
        raise RuntimeError(
            f"Résultat suspect ({dungeons} donjons, {raids} raids) : la page du wiki a peut-être changé."
        )
    return instances


# --------------------------------------------------------------------------- registre


class InstanceRegistry:
    def __init__(self, cache_path: Path):
        self.cache_path = cache_path
        self._instances: list[Instance] = []
        self.updated_at: datetime | None = None
        self.source = "liste intégrée"

    @property
    def all(self) -> list[Instance]:
        return list(self._instances)

    def load(self) -> None:
        for path, source in ((self.cache_path, "wiki (cache)"), (DEFAULT_PATH, "liste intégrée")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                instances = [Instance(**item) for item in data["instances"]]
            except FileNotFoundError:
                continue
            except (OSError, ValueError, KeyError, TypeError) as exc:
                log.warning("Impossible de lire %s : %s", path, exc)
                continue
            if instances:
                self._set(instances, data.get("updated_at"), source)
                log.info("%d instances chargées depuis %s", len(instances), path)
                return
        log.error("Aucune liste d'instances disponible.")

    def _set(self, instances: list[Instance], updated_at: str | None, source: str) -> None:
        # Donjons triés par niveau, puis raids par taille.
        def key(i: Instance) -> tuple:
            lvl = re.match(r"\d+", i.levels or "")
            return (i.kind == "raid", i.size if i.is_raid else int(lvl.group()) if lvl else 99, i.name)

        self._instances = sorted(instances, key=key)
        self.updated_at = datetime.fromisoformat(updated_at) if updated_at else None
        self.source = source

    def cache_age_hours(self) -> float | None:
        if self.updated_at is None or self.source != "wiki (cache)":
            return None
        return (datetime.now(timezone.utc) - self.updated_at).total_seconds() / 3600

    async def refresh(self, session: aiohttp.ClientSession) -> int:
        instances = await fetch_from_wiki(session)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        payload = {"source": WIKI_URL, "updated_at": now, "instances": [asdict(i) for i in instances]}
        tmp = self.cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.cache_path)
        self._set(instances, now, "wiki (cache)")
        return len(instances)

    def get(self, query: str) -> Instance | None:
        q = query.strip().lower()
        for inst in self._instances:
            if inst.name.lower() == q:
                return inst
        for inst in self._instances:
            if inst.abbr and q in {a.strip().lower() for a in inst.abbr.split("/")}:
                return inst
        return None

    def search(self, query: str, limit: int = 25) -> list[Instance]:
        q = query.strip().lower()
        if not q:
            return self._instances[:limit]

        def score(inst: Instance) -> int | None:
            name, abbr = inst.name.lower(), inst.abbr.lower()
            if abbr == q or name == q:
                return 0
            if name.startswith(q) or abbr.startswith(q):
                return 1
            if q in name or q in abbr or q in inst.location.lower():
                return 2
            return None

        scored = [(s, i) for i in self._instances if (s := score(i)) is not None]
        scored.sort(key=lambda t: t[0])  # tri stable : garde l'ordre niveau/taille
        return [i for _, i in scored[:limit]]
