"""Client WoW Planner : fait le lien entre l'addon WowPlanner et le site (le jeu ne laisse pas les addons parler au
réseau).

- Installe l'addon dans Interface/AddOns du dossier du jeu choisi, et le met à jour quand le site en a une version
  plus récente (vérifié avec les prix ; en jeu, /reload pour la prendre).
- Toutes les 20 minutes, télécharge les prix de l'hôtel des ventes et les quêtes de donjon, et les écrit dans
  Data.lua (pris par le jeu à la connexion ou au /reload : « /wp maj » en jeu).
- Dès que le jeu enregistre ce que l'addon a vu (déconnexion, /reload), envoie l'inventaire, les métiers, les
  recettes et les relevés de la chasse au trésor (donneurs de quêtes, suites de quêtes) au site.

Python 3.10+, sans dépendance (tkinter pour la fenêtre). `--once` : une synchro sans fenêtre (réglages déjà
enregistrés), pour tester ou lancer depuis une tâche planifiée.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import queue
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable

VERSION = "1.4.0"
SITE_URL = "https://wow.raug-info.ch"
REPO_URL = "https://github.com/raugdae/wowplanner"
TERMS_VERSION = "4"  # à changer si les conditions ci-dessous changent : elles sont alors redemandées
TERMS = f"""WoW Planner (client {VERSION} et addon) est gratuit, sans publicité ni abonnement, et libre : licence MIT,
tu peux l'utiliser, le copier, le modifier et le partager en gardant cette licence.

Il est fourni « tel quel », SANS AUCUNE GARANTIE. Tu l'utilises à tes risques : dans les limites permises par la
loi, l'auteur n'est responsable d'aucun dommage, perte de données ou problème lié à son utilisation, y compris avec
ton compte de jeu.

Ce que fait le client : il se met à jour tout seul depuis le dépôt GitHub du projet, il installe l'addon dans le
dossier du jeu que tu choisis et le met à jour depuis le site,
y écrit les prix de l'hôtel des ventes et les quêtes de donjon, et envoie au site, avec ton jeton, ce que l'addon
a noté pour tes persos déclarés (sacs, banque, argent, niveau, métiers, recettes) ainsi que les quêtes que les PNJ
t'ont proposées (PNJ, ta position à ce moment-là, niveaux, suites de quêtes) pour la chasse au trésor de la guilde. Rien d'autre ne quitte ton ordinateur. Détails : page Confidentialité du site.

Projet de fans, sans lien avec Blizzard Entertainment ni WoW Forever.

Fait par Raugdae pour la guilde. Logo créé par ideapub (ideapub.ch).
Développé avec l'aide de l'IA : Claude Code, l'assistant de programmation d'Anthropic.

Licence complète et code source : {REPO_URL}"""
DEFAULT_SERVER = "https://wow.raug-info.ch"
PRICES_EVERY = 20 * 60
WATCH_EVERY = 15
ADDON_NAME = "WowPlanner"
# Mise à jour du client : dernière release GitHub (tag client-vX.Y.Z), vérifiée toutes les 6 heures.
RELEASES_API = (os.environ.get("WOWPLANNER_RELEASES_API")  # tests : une fausse release locale
                or "https://api.github.com/repos/raugdae/wowplanner/releases/latest")
CLIENT_ASSETS = {"win32": "WowPlanner-Windows.zip", "darwin": "WowPlanner-macOS.zip"}
CLIENT_CHECK_EVERY = 6 * 3600
MAX_CLIENT_SIZE = 80 * 1024 * 1024
MAX_ADDON_SIZE = 5 * 1024 * 1024  # garde-fou : l'addon pèse quelques dizaines de Ko (hors prix)
ADDON_FILE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")  # fichiers à plat dans WowPlanner/, sans chemin
GAME_FOLDERS = ("_classic_era_", "_classic_", "_anniversary_", "_retail_")


# ====================================================================== réglages


def config_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home()) / "WowPlanner"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "WowPlanner"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "wowplanner"


@dataclass
class Settings:
    server: str = DEFAULT_SERVER
    token: str = ""
    game_dir: str = ""
    prices_etag: str = ""
    accepted: str = ""  # version des conditions acceptées (TERMS_VERSION)
    sent: dict[str, float] = field(default_factory=dict)  # fichier SavedVariables -> date du dernier envoi

    @classmethod
    def load(cls) -> Settings:
        try:
            raw = json.loads((config_dir() / "config.json").read_text(encoding="utf-8"))
            return cls(**{k: v for k, v in raw.items() if k in cls.__dataclass_fields__})
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self) -> None:
        folder = config_dir()
        folder.mkdir(parents=True, exist_ok=True)
        tmp = folder / "config.json.tmp"
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        os.replace(tmp, folder / "config.json")


# ====================================================================== dossiers du jeu


def game_root(chosen: str | Path) -> Path | None:
    """Dossier de la version du jeu (celui qui contient Interface et WTF) à partir du dossier choisi : lui-même, ou
    _classic_era_ & co. dedans, ou son parent si on a choisi Interface ou AddOns."""
    path = Path(chosen).expanduser()
    if not path.is_dir():
        return None
    for candidate in (path, *(path / name for name in GAME_FOLDERS), *path.parents[:2]):
        if (candidate / "WTF").is_dir() or (candidate / "Interface").is_dir():
            return candidate
    # Jeu jamais lancé avec des addons : un dossier qui contient l'exécutable fait l'affaire.
    if any(p.suffix.lower() in (".exe", ".app") and p.name.lower().startswith("wow") for p in path.iterdir()):
        return path
    return None


def addons_dir(root: Path) -> Path:
    return root / "Interface" / "AddOns"


def saved_variables(root: Path) -> list[Path]:
    """Fichiers enregistrés par l'addon, un par compte (WTF/Account/<compte>/SavedVariables/WowPlanner.lua)."""
    return sorted((root / "WTF" / "Account").glob(f"*/SavedVariables/{ADDON_NAME}.lua"))


def bundled_addon() -> Path:
    """Dossier de l'addon livré avec le client (dans l'exécutable, ou à côté dans le dépôt)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "addon" / ADDON_NAME


def bundled_file(name: str) -> Path:
    """Fichier livré avec le client (logo…), dans l'exécutable ou à côté du script."""
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) / "client" / name if base else Path(__file__).resolve().parent / name


def parse_version(text: str | None) -> tuple[int, ...]:
    """« 1.0.3 » → (1, 0, 3) ; () si illisible (donc plus ancienne que tout)."""
    return tuple(int(n) for n in re.findall(r"\d+", text or "")[:4])


def addon_version(folder: Path) -> str | None:
    """Version d'un addon (ligne « ## Version: » de son .toc), None s'il n'y en a pas."""
    try:
        text = (folder / f"{ADDON_NAME}.toc").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = re.search(r"^## Version:\s*(\S+)", text, re.MULTILINE)
    return match.group(1) if match else None


def install_addon(root: Path, source: Path | None = None) -> bool:
    """Copie l'addon dans le jeu (sans écraser les prix déjà téléchargés). True si quelque chose a changé.

    Rien n'est fait si le jeu a déjà une version plus récente (mise à jour reçue du site) : l'addon livré avec le
    client ne doit pas la remplacer par une plus ancienne."""
    source = source or bundled_addon()
    target = addons_dir(root) / ADDON_NAME
    if parse_version(addon_version(target)) > parse_version(addon_version(source)):
        return False
    target.mkdir(parents=True, exist_ok=True)
    changed = False
    for path in source.iterdir():
        if not path.is_file():
            continue
        dest = target / path.name
        if path.name == "Data.lua" and dest.exists():
            continue
        if not dest.exists() or dest.read_bytes() != path.read_bytes():
            shutil.copyfile(path, dest)
            changed = True
    return changed


def install_addon_zip(root: Path, archive: bytes) -> bool:
    """Pose dans le jeu l'addon reçu du site (.zip avec un dossier WowPlanner/), sans écraser les prix.

    L'archive est vérifiée avant d'écrire quoi que ce soit : fichiers à plat dans WowPlanner/ uniquement (aucun
    chemin qui sortirait du dossier de l'addon), taille raisonnable, .toc présent. ValueError sinon."""
    files: dict[str, bytes] = {}
    total = 0
    with zipfile.ZipFile(io.BytesIO(archive)) as content:
        for info in content.infolist():
            if info.is_dir():
                continue
            parts = PurePosixPath(info.filename).parts
            if len(parts) != 2 or parts[0] != ADDON_NAME or not ADDON_FILE.match(parts[1]):
                raise ValueError(f"fichier inattendu dans l'archive : {info.filename}")
            total += info.file_size
            if total > MAX_ADDON_SIZE:
                raise ValueError("archive trop grosse")
            files[parts[1]] = content.read(info)
    if f"{ADDON_NAME}.toc" not in files:
        raise ValueError("archive sans fichier .toc")
    target = addons_dir(root) / ADDON_NAME
    target.mkdir(parents=True, exist_ok=True)
    changed = False
    for name, data in files.items():
        dest = target / name
        if (name == "Data.lua" and dest.exists()) or (dest.exists() and dest.read_bytes() == data):
            continue
        tmp = dest.with_name(name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, dest)
        changed = True
    return changed


# ====================================================================== Lua


class LuaError(ValueError):
    pass


_TOKEN = re.compile(
    r"""\s*(?:--\[(=*)\[.*?\]\1\]|--[^\n]*|
    (?P<str>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')|
    (?P<num>-?(?:0[xX][0-9a-fA-F]+|\d+\.?\d*(?:[eE][-+]?\d+)?|\.\d+(?:[eE][-+]?\d+)?))|
    (?P<name>[A-Za-z_][A-Za-z0-9_]*)|
    (?P<sym>[{}\[\]=,;]))""",
    re.S | re.X,
)
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "f": "\f", "v": "\v", "\\": "\\", '"': '"',
            "'": "'", "\n": "\n"}


def _unescape(body: str) -> str:
    """Contenu d'une chaîne Lua, séquences d'échappement comprises (dont les octets en décimal)."""
    data = bytearray()
    i = 0
    while i < len(body):
        ch = body[i]
        if ch != "\\":
            data += ch.encode("utf-8")
            i += 1
            continue
        nxt = body[i + 1]
        if nxt.isdigit():
            digits = re.match(r"\d{1,3}", body[i + 1:]).group()
            data.append(int(digits) & 0xFF)
            i += 1 + len(digits)
        else:
            data += _ESCAPES.get(nxt, nxt).encode("utf-8")
            i += 2
    return data.decode("utf-8", "replace")


def parse_lua_assignments(text: str) -> dict[str, Any]:
    """Variables d'un fichier SavedVariables (NOM = valeur, tables imbriquées) en objets Python : une table dont
    toutes les clés sont 1..n devient une liste, les autres des dict."""
    tokens: list[tuple[str, Any]] = []
    pos = 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m:
            if text[pos:].strip():
                raise LuaError(f"caractère inattendu à la position {pos}")
            break
        pos = m.end()
        if m.group("str") is not None:
            tokens.append(("v", _unescape(m.group("str")[1:-1])))
        elif m.group("num") is not None:
            raw = m.group("num")
            if raw.lower().lstrip("-").startswith("0x"):
                tokens.append(("v", int(raw, 16)))
            elif re.fullmatch(r"-?\d+", raw):
                tokens.append(("v", int(raw)))
            else:
                tokens.append(("v", float(raw)))
        elif m.group("name") is not None:
            word = m.group("name")
            tokens.append(("v", {"true": True, "false": False, "nil": None}[word]) if word in ("true", "false", "nil")
                          else ("n", word))
        elif m.group("sym") is not None:
            tokens.append(("s", m.group("sym")))
    i = 0

    def peek(kind: str, value: Any = None) -> bool:
        return i < len(tokens) and tokens[i][0] == kind and (value is None or tokens[i][1] == value)

    def expect(kind: str, value: Any = None) -> Any:
        nonlocal i
        if not peek(kind, value):
            raise LuaError(f"attendu {value or kind} (jeton {i})")
        i += 1
        return tokens[i - 1][1]

    def value() -> Any:
        nonlocal i
        if peek("v"):
            i += 1
            return tokens[i - 1][1]
        if peek("s", "{"):
            return table()
        raise LuaError(f"valeur attendue (jeton {i})")

    def table() -> Any:
        nonlocal i
        expect("s", "{")
        result: dict[Any, Any] = {}
        n = 0
        while not peek("s", "}"):
            if peek("s", "["):
                i += 1
                key = value()
                expect("s", "]")
                expect("s", "=")
                result[key] = value()
            elif peek("n") and i + 1 < len(tokens) and tokens[i + 1] == ("s", "="):
                key = tokens[i][1]
                i += 2
                result[key] = value()
            else:
                n += 1
                result[n] = value()
            if peek("s", ",") or peek("s", ";"):
                i += 1
        expect("s", "}")
        if result and all(isinstance(k, int) for k in result) and sorted(result) == list(range(1, len(result) + 1)):
            return [result[k] for k in range(1, len(result) + 1)]
        return result

    variables: dict[str, Any] = {}
    while i < len(tokens):
        name = expect("n")
        expect("s", "=")
        variables[name] = value()
    return variables


def lua_prices(data: dict[str, Any]) -> str:
    """Data.lua de l'addon à partir de la réponse de /api/addon/prix."""
    lines = [
        "-- Prix de l'hôtel des ventes, écrits par le client WoW Planner : ne pas modifier (remplacé à chaque mise à jour).",
        f"WowPlannerData = {{ ts = {int(data.get('ts') or 0)}, generated = {int(data.get('generated') or 0)}, items = {{",
    ]
    for row in data.get("items") or []:
        item, low, median, sold = (int(v) for v in row[:4])
        lines.append(f"[{item}]={{{low},{median},{sold}}},")
    lines.append("} }")
    return "\n".join(lines) + "\n"


def inventory_payload(saved: dict[str, Any]) -> dict[str, Any]:
    """Persos enregistrés par l'addon (WowPlannerDB.chars) au format attendu par /api/addon/inventaire."""
    db = saved.get("WowPlannerDB")
    chars = db.get("chars") if isinstance(db, dict) else None
    out = []
    for entry in (chars or {}).values():
        if not isinstance(entry, dict) or not entry.get("name"):
            continue
        counts = lambda raw: {str(k): v for k, v in raw.items()} if isinstance(raw, dict) else {}  # noqa: E731
        recipes = None
        if isinstance(entry.get("recipes"), dict):
            recipes = {
                prof: [r for r in (items.values() if isinstance(items, dict) else items) if isinstance(r, dict)]
                for prof, items in entry["recipes"].items()
            }
        out.append({
            "name": entry["name"], "realm": entry.get("realm"), "level": entry.get("level"),
            "money": entry.get("money"), "updated_at": entry.get("updated"), "bags": counts(entry.get("bags")),
            "bank": counts(entry["bank"]) if isinstance(entry.get("bank"), dict) else None,
            "bank_at": entry.get("bankAt"), "professions": entry.get("professions") or None, "recipes": recipes,
        })
    return {"client": VERSION, "characters": out, "hunt": hunt_payload(db)}


def hunt_payload(db: Any) -> dict[str, Any]:
    """Relevés de la chasse au trésor (WowPlannerDB.hunt) : quêtes vues en jeu et suites de quêtes."""
    hunt = db.get("hunt") if isinstance(db, dict) else None
    if not isinstance(hunt, dict):
        return {"quests": [], "links": []}
    quests = []
    for qid, entry in (hunt.get("quests") or {}).items():
        if isinstance(entry, dict) and str(qid).isdigit():
            quests.append({**entry, "id": int(qid)})
    links = []
    for key in (hunt.get("links") or {}):
        prev, _, nxt = str(key).partition(">")
        if prev.isdigit() and nxt.isdigit():
            links.append([int(prev), int(nxt)])
    return {"quests": quests, "links": links}


# ====================================================================== site


class ApiError(Exception):
    pass


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi  # présent dans l'exécutable (certificats à jour sur macOS)
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


class Api:
    def __init__(self, server: str, token: str):
        self.server, self.token = server.rstrip("/"), token.strip()
        self._ssl = _ssl_context()

    def request(self, method: str, path: str, body: Any = None,
                headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.server + path, data=data, method=method, headers={
            "Authorization": f"Bearer {self.token}", "User-Agent": f"WowPlannerClient/{VERSION}",
            "Accept-Encoding": "identity", **({"Content-Type": "application/json"} if data else {}), **(headers or {}),
        })
        try:
            with urllib.request.urlopen(req, timeout=60, context=self._ssl) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 304:
                return 304, dict(exc.headers), b""
            try:
                message = json.loads(exc.read()).get("error") or exc.reason
            except ValueError:
                message = exc.reason
            raise ApiError(f"{exc.code} : {message}") from None
        except (urllib.error.URLError, OSError) as exc:
            raise ApiError(f"site injoignable ({getattr(exc, 'reason', exc)})") from None

    def me(self) -> dict[str, Any]:
        return json.loads(self.request("GET", "/api/addon/moi")[2])


# ====================================================================== mise à jour du client


def frozen_target() -> Path | None:
    """Ce qu'il faut remplacer pour mettre le client à jour : l'exécutable (Windows) ou l'app (macOS). None si le
    client tourne depuis ses sources (python wowplanner_client.py) : pas de mise à jour automatique."""
    if not getattr(sys, "frozen", False):
        return None
    exe = Path(sys.executable).resolve()
    if sys.platform == "darwin":
        return next((parent for parent in exe.parents if parent.suffix == ".app"), None)
    return exe


def release_asset(release: Any, platform: str = sys.platform) -> tuple[str, str, str | None] | None:
    """(version, adresse du .zip, empreinte « sha256:… » ou None) de la dernière release GitHub du client pour ce
    système ; None si elle ne le concerne pas."""
    if not isinstance(release, dict):
        return None
    tag = str(release.get("tag_name") or "")
    if not tag.startswith("client-v"):
        return None
    wanted = CLIENT_ASSETS.get(platform)
    for asset in release.get("assets") or []:
        if isinstance(asset, dict) and asset.get("name") == wanted and asset.get("browser_download_url"):
            return tag.removeprefix("client-v"), str(asset["browser_download_url"]), asset.get("digest")
    return None


def fetch(url: str, accept: str = "application/octet-stream", limit: int = MAX_CLIENT_SIZE) -> bytes:
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": f"WowPlannerClient/{VERSION}"})
    try:
        with urllib.request.urlopen(req, timeout=120, context=_ssl_context()) as resp:
            data = resp.read(limit + 1)
    except (urllib.error.URLError, OSError) as exc:
        raise ApiError(f"GitHub injoignable ({getattr(exc, 'reason', exc)})") from None
    if len(data) > limit:
        raise ApiError("fichier trop gros")
    return data


def check_digest(data: bytes, digest: str | None) -> None:
    """Vérifie l'empreinte publiée par GitHub pour le fichier (« sha256:… ») : un téléchargement abîmé ou modifié
    en route est refusé."""
    if not digest:
        return
    kind, _, value = digest.partition(":")
    if kind != "sha256" or hashlib.sha256(data).hexdigest() != value.lower():
        raise ValueError("empreinte du téléchargement incorrecte")


def apply_client_update(target: Path, archive: bytes, platform: str = sys.platform) -> Path:
    """Remplace le client par celui de l'archive de la release (WowPlanner/WowPlanner.exe ou WowPlanner.app).
    L'ancien est gardé à côté (« .old ») jusqu'au prochain lancement : un programme lancé ne peut pas s'effacer, mais
    il peut se renommer. Renvoie ce qu'il faut relancer."""
    with zipfile.ZipFile(io.BytesIO(archive)) as content:
        names = content.namelist()
        if platform == "darwin":
            if not any(n.startswith("WowPlanner/WowPlanner.app/") for n in names):
                raise ValueError("archive sans WowPlanner.app")
            with tempfile.TemporaryDirectory() as tmp:
                zipped = Path(tmp) / "client.zip"
                zipped.write_bytes(archive)
                # ditto garde les droits d'exécution et les liens de l'app (zipfile les perdrait).
                subprocess.run(["ditto", "-x", "-k", str(zipped), str(Path(tmp) / "out")], check=True)
                fresh = Path(tmp) / "out" / "WowPlanner" / "WowPlanner.app"
                old = target.with_name(target.stem + ".old.app")
                shutil.rmtree(old, ignore_errors=True)
                os.replace(target, old)
                shutil.move(str(fresh), str(target))
            return target
        member = next((n for n in names if n.replace("\\", "/").endswith("WowPlanner/WowPlanner.exe")), None)
        if member is None:
            raise ValueError("archive sans WowPlanner.exe")
        data = content.read(member)
    if not data.startswith(b"MZ"):
        raise ValueError("exécutable illisible")
    fresh = target.with_name(target.stem + ".new" + target.suffix)
    old = target.with_name(target.stem + ".old" + target.suffix)
    fresh.write_bytes(data)
    try:
        old.unlink()
    except OSError:
        pass
    os.replace(target, old)
    os.replace(fresh, target)
    return target


def remove_old_client(target: Path | None = None, tries: int = 10, pause: float = 3.0) -> None:
    """Efface l'ancienne version laissée par la dernière mise à jour (au lancement de la nouvelle ; elle peut mettre
    quelques secondes à se fermer, d'où les essais répétés)."""
    target = target or frozen_target()
    if target is None:
        return
    old = target.with_name(target.stem + ".old" + target.suffix)
    for attempt in range(tries):
        try:
            if old.is_dir():
                shutil.rmtree(old)
            elif old.exists():
                old.unlink()
            return
        except OSError:
            if attempt + 1 < tries:
                time.sleep(pause)


def relaunch(target: Path) -> None:
    """Lance la nouvelle version (environnement PyInstaller remis à zéro : elle se décompresse dans son propre
    dossier) ; l'appelant se ferme ensuite."""
    env = {**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"}
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-n", str(target)], env=env)
    else:
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen([str(target)], env=env, creationflags=flags, close_fds=True)


# ====================================================================== synchro


class Sync:
    """Une passe de synchro : addon, prix (si l'heure est venue), inventaire (si le jeu a enregistré)."""

    def __init__(self, settings: Settings, log: Callable[[str], None]):
        self.settings, self.log = settings, log
        self.last_prices = 0.0
        self.last_client_check = 0.0
        self.told_version: str | None = None
        # Appelé avec le client mis à jour à relancer (fenêtre) ; None : mise à jour seulement signalée (--once).
        self.restart: Callable[[Path], None] | None = None

    def update_client(self) -> bool:
        """Installe la dernière version du client si GitHub en a une plus récente. True si le client doit redémarrer."""
        self.last_client_check = time.time()
        try:
            found = release_asset(json.loads(fetch(RELEASES_API, "application/vnd.github+json", 1_000_000)))
        except (ApiError, ValueError):
            return False  # GitHub injoignable : on réessaiera plus tard, sans encombrer le journal
        if found is None or parse_version(found[0]) <= parse_version(VERSION):
            return False
        version, url, digest = found
        target = frozen_target()
        if target is None or self.restart is None:
            if self.told_version != version:
                self.told_version = version
                self.log(f"Nouvelle version du client disponible : {version} ({REPO_URL}/releases/latest).")
            return False
        self.log(f"Nouvelle version du client : {VERSION} → {version}, téléchargement…")
        try:
            archive = fetch(url)
            check_digest(archive, digest)
            target = apply_client_update(target, archive)
        except (ApiError, ValueError, OSError, zipfile.BadZipFile, subprocess.CalledProcessError) as exc:
            self.log(f"Client non mis à jour : {exc}")
            return False
        self.log(f"Client {version} installé : redémarrage…")
        self.restart(target)
        return True

    def root(self) -> Path | None:
        return game_root(self.settings.game_dir) if self.settings.game_dir else None

    def run(self, force_prices: bool = False) -> None:
        if time.time() - self.last_client_check >= CLIENT_CHECK_EVERY and self.update_client():
            return  # le client redémarre dans sa nouvelle version
        root = self.root()
        if root is None:
            self.log("Choisis le dossier du jeu.")
            return
        if not self.settings.token:
            self.log("Colle ton jeton (page Addon WoW du site).")
            return
        api = Api(self.settings.server, self.settings.token)
        try:
            if install_addon(root):
                self.log("Addon installé / mis à jour dans Interface/AddOns (en jeu : /reload).")
        except OSError as exc:
            self.log(f"Impossible d'installer l'addon : {exc}")
        if force_prices or time.time() - self.last_prices >= PRICES_EVERY:
            self.update_addon(api, root)
            self.prices(api, root, force_prices)
        self.inventory(api, root)

    def update_addon(self, api: Api, root: Path) -> None:
        """Installe l'addon du site s'il est plus récent que celui du jeu."""
        try:
            remote = json.loads(api.request("GET", "/api/addon/version")[2])
        except ApiError as exc:
            if not str(exc).startswith("404"):  # site plus ancien, sans mise à jour de l'addon : rien à dire
                self.log(f"Mise à jour de l'addon non vérifiée : {exc}")
            return
        except ValueError:
            return
        installed = addon_version(addons_dir(root) / ADDON_NAME)
        if parse_version(remote.get("version")) <= parse_version(installed):
            return
        try:
            archive = api.request("GET", "/api/addon/zip")[2]
            if hashlib.sha256(archive).hexdigest() != remote.get("sha256"):
                raise ValueError("archive abîmée pendant le téléchargement")
            install_addon_zip(root, archive)
        except (ApiError, ValueError, zipfile.BadZipFile, OSError) as exc:
            self.log(f"Addon non mis à jour : {exc}")
            return
        self.log(f"Addon mis à jour : {installed or '?'} → {remote['version']} (en jeu : /reload pour le prendre).")

    def prices(self, api: Api, root: Path, force: bool = False) -> None:
        """Data.lua de l'addon (prix de l'HdV et quêtes de donjon), écrit tel que le site le prépare."""
        headers = {} if force or not self.settings.prices_etag else {"If-None-Match": self.settings.prices_etag}
        try:
            status, resp_headers, body = api.request("GET", "/api/addon/data", headers=headers)
        except ApiError as exc:
            if str(exc).startswith("404"):  # site plus ancien : prix seuls
                self.legacy_prices(api, root, force)
            else:
                self.log(f"Prix non téléchargés : {exc}")
            return
        self.last_prices = time.time()
        if status == 304:
            self.log("Prix et quêtes : rien de nouveau.")
            return
        text = body.decode("utf-8", errors="replace")
        if "WowPlannerData = {" not in text:
            self.log("Données du site illisibles : rien d'écrit.")
            return
        self.write_data(root, text)
        self.settings.prices_etag = resp_headers.get("ETag", "")
        self.settings.save()
        ts = re.search(r"ts = (\d+)", text)
        when = datetime.fromtimestamp(int(ts.group(1)) if ts else 0).strftime("%d/%m %H:%M")
        hunt = re.search(r"found = (\d+), total = (\d+)", text)
        quests = f", quêtes de donjon : {hunt.group(1)}/{hunt.group(2)} repérées" if hunt else ""
        self.log(f"Prix du {when}{quests} : en jeu, /wp maj pour les prendre.")

    @staticmethod
    def write_data(root: Path, text: str) -> None:
        target = addons_dir(root) / ADDON_NAME / "Data.lua"
        tmp = target.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, target)

    def legacy_prices(self, api: Api, root: Path, force: bool = False) -> None:
        try:
            headers = {} if force or not self.settings.prices_etag else {"If-None-Match": self.settings.prices_etag}
            status, resp_headers, body = api.request("GET", "/api/addon/prix", headers=headers)
        except ApiError as exc:
            self.log(f"Prix non téléchargés : {exc}")
            return
        self.last_prices = time.time()
        if status == 304:
            self.log("Prix : pas de nouveau relevé.")
            return
        data = json.loads(body)
        self.write_data(root, lua_prices(data))
        self.settings.prices_etag = resp_headers.get("ETag", "")
        self.settings.save()
        when = datetime.fromtimestamp(data.get("ts") or 0).strftime("%d/%m %H:%M")
        self.log(f"Prix du {when} écrits ({len(data.get('items') or [])} objets) : en jeu, /wp maj pour les prendre.")

    def inventory(self, api: Api, root: Path) -> None:
        for path in saved_variables(root):
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            key = str(path)
            if self.settings.sent.get(key) == mtime:
                continue
            try:
                payload = inventory_payload(parse_lua_assignments(path.read_text(encoding="utf-8", errors="replace")))
            except LuaError as exc:
                self.log(f"{path.parent.parent.name} : fichier de l'addon illisible ({exc}).")
                self.settings.sent[key] = mtime
                continue
            if not payload["characters"]:
                self.settings.sent[key] = mtime
                continue
            try:
                result = json.loads(api.request("POST", "/api/addon/inventaire", payload)[2])
            except ApiError as exc:
                self.log(f"Inventaire non envoyé : {exc}")
                return
            self.settings.sent[key] = mtime
            self.settings.save()
            if result.get("updated"):
                self.log("Inventaire envoyé : " + ", ".join(result["updated"]) + ".")
            if result.get("unknown"):
                self.log("Persos inconnus du site (à ajouter dans Mes persos) : " + ", ".join(result["unknown"]) + ".")
            hunt = result.get("hunt") or {}
            if hunt.get("discovered"):
                dungeon = hunt.get("dungeon") or []
                extra = f" dont, pour les donjons : {', '.join(dungeon[:5])}" if dungeon else ""
                self.log(f"🔎 Chasse au trésor : {hunt['discovered']} quête(s) repérée(s) pour la première fois{extra} !")
            if hunt.get("links"):
                self.log(f"🔗 Chasse au trésor : {hunt['links']} suite(s) de quêtes découverte(s) !")


# ====================================================================== fenêtre


def run_window(settings: Settings) -> None:
    import tkinter as tk
    from tkinter import filedialog, ttk

    messages: queue.Queue[str] = queue.Queue()
    log = lambda text: messages.put(f"{datetime.now():%H:%M:%S}  {text}")  # noqa: E731
    sync = Sync(settings, log)

    def restart(target: Path) -> None:  # appelé par le fil de synchro : la fenêtre se ferme depuis le sien
        def go() -> None:
            try:
                relaunch(target)
            except OSError as exc:
                log(f"Relance impossible ({exc}) : relance WoW Planner à la main.")
                return
            window.destroy()
            os._exit(0)
        window.after(1500, go)

    sync.restart = restart
    wake = threading.Event()
    force = threading.Event()

    def worker() -> None:
        last = 0.0
        while True:
            wake.wait(WATCH_EVERY)
            wake.clear()
            forced = force.is_set()
            force.clear()
            if forced or time.time() - last >= WATCH_EVERY:
                try:
                    sync.run(force_prices=forced)
                except Exception as exc:  # la boucle ne doit jamais s'arrêter
                    log(f"Erreur : {exc}")
                last = time.time()

    window = tk.Tk()
    window.title(f"WoW Planner {VERSION}")
    window.minsize(600, 460)
    logo = None
    try:
        logo = tk.PhotoImage(file=str(bundled_file("logo.png")))
        window.iconphoto(True, logo)
    except (tk.TclError, OSError):
        pass

    def show_terms(first_time: bool) -> bool:
        """Conditions d'utilisation (et à propos) ; au premier lancement, il faut les accepter pour continuer."""
        import webbrowser

        dialog = tk.Toplevel(window)
        dialog.title("Conditions d'utilisation" if first_time else "À propos de WoW Planner")
        box = ttk.Frame(dialog, padding=14)
        box.pack(fill="both", expand=True)
        if logo is not None:
            small = logo.subsample(4)
            picture = ttk.Label(box, image=small)
            picture.image = small  # garder une référence
            picture.pack(anchor="w")
        ttk.Label(box, text=f"WoW Planner {VERSION}", font=("TkDefaultFont", 13, "bold")).pack(anchor="w", pady=(4, 8))
        text = tk.Text(box, width=86, height=20, wrap="word")
        text.insert("1.0", TERMS)
        text.configure(state="disabled")
        text.pack(fill="both", expand=True)
        result = {"ok": not first_time}
        row = ttk.Frame(box)
        row.pack(fill="x", pady=(10, 0))

        def close(ok: bool) -> None:
            result["ok"] = ok or not first_time
            dialog.destroy()

        ttk.Button(row, text="Code source et licence", command=lambda: webbrowser.open(REPO_URL)).pack(side="left")
        ttk.Button(row, text="Site", command=lambda: webbrowser.open(SITE_URL)).pack(side="left", padx=6)
        if first_time:
            ttk.Button(row, text="Quitter", command=lambda: close(False)).pack(side="right")
            ttk.Button(row, text="J'accepte", command=lambda: close(True)).pack(side="right", padx=6)
        else:
            ttk.Button(row, text="Fermer", command=lambda: close(True)).pack(side="right")
        dialog.protocol("WM_DELETE_WINDOW", lambda: close(False))
        dialog.grab_set()
        window.wait_window(dialog)
        return result["ok"]

    if settings.accepted != TERMS_VERSION:
        window.withdraw()
        if not show_terms(True):
            window.destroy()
            return
        settings.accepted = TERMS_VERSION
        settings.save()
        window.deiconify()

    frame = ttk.Frame(window, padding=12)
    frame.pack(fill="both", expand=True)
    frame.columnconfigure(1, weight=1)

    header = ttk.Frame(frame)
    header.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 10))
    if logo is not None:
        icon = logo.subsample(5)
        picture = ttk.Label(header, image=icon)
        picture.image = icon
        picture.pack(side="left", padx=(0, 10))
    titles = ttk.Frame(header)
    titles.pack(side="left")
    ttk.Label(titles, text="WoW Planner", font=("TkDefaultFont", 15, "bold"), foreground="#5f07b6").pack(anchor="w")
    ttk.Label(titles, text="Le lien entre l'addon et le site de la guilde", foreground="#666").pack(anchor="w")
    ttk.Button(header, text="À propos", command=lambda: show_terms(False)).pack(side="right")

    server = tk.StringVar(value=settings.server)
    token = tk.StringVar(value=settings.token)
    game = tk.StringVar(value=settings.game_dir)
    found = tk.StringVar()

    def show_root(*_: Any) -> None:
        root = game_root(game.get()) if game.get() else None
        if root is None:
            found.set("Dossier du jeu introuvable : choisis celui qui contient Interface et WTF.")
        else:
            accounts = len(saved_variables(root))
            found.set(f"Jeu : {root}" + (f" · {accounts} compte(s) avec l'addon" if accounts else ""))

    def browse() -> None:
        chosen = filedialog.askdirectory(title="Dossier du jeu (celui qui contient Interface et WTF)",
                                         initialdir=game.get() or None, mustexist=True)
        if chosen:
            game.set(chosen)
            show_root()

    def save_and_sync() -> None:
        settings.server, settings.token, settings.game_dir = server.get().strip(), token.get().strip(), game.get()
        settings.save()
        show_root()

        def check() -> None:
            try:
                names = Api(settings.server, settings.token).me().get("characters") or []
                log("Connecté au site. Tes persos : " + (", ".join(names) or "aucun") + ".")
            except ApiError as exc:
                log(f"Connexion au site impossible : {exc}")
            force.set()
            wake.set()

        threading.Thread(target=check, daemon=True).start()

    ttk.Label(frame, text="Site").grid(row=1, column=0, sticky="w", pady=3)
    ttk.Entry(frame, textvariable=server).grid(row=1, column=1, columnspan=2, sticky="ew", pady=3)
    ttk.Label(frame, text="Jeton").grid(row=2, column=0, sticky="w", pady=3)
    ttk.Entry(frame, textvariable=token, show="•").grid(row=2, column=1, columnspan=2, sticky="ew", pady=3)
    ttk.Label(frame, text="Dossier du jeu").grid(row=3, column=0, sticky="w", pady=3)
    ttk.Entry(frame, textvariable=game).grid(row=3, column=1, sticky="ew", pady=3)
    ttk.Button(frame, text="Parcourir…", command=browse).grid(row=3, column=2, padx=(6, 0), pady=3)
    ttk.Label(frame, textvariable=found, foreground="#666").grid(row=4, column=0, columnspan=3, sticky="w")
    buttons = ttk.Frame(frame)
    buttons.grid(row=5, column=0, columnspan=3, sticky="w", pady=(8, 8))
    ttk.Button(buttons, text="Enregistrer et synchroniser", command=save_and_sync).pack(side="left")
    ttk.Label(buttons, text="  Prix toutes les 20 min · inventaire envoyé après chaque /reload ou déconnexion",
              foreground="#666").pack(side="left")
    journal = tk.Text(frame, height=14, wrap="word", state="disabled")
    journal.grid(row=6, column=0, columnspan=3, sticky="nsew")
    frame.rowconfigure(6, weight=1)
    ttk.Label(frame, text="Gratuit et libre (MIT), sans garantie · logo : ideapub · développé avec l'IA Claude Code",
              foreground="#888").grid(row=7, column=0, columnspan=3, sticky="w", pady=(6, 0))

    def pump() -> None:
        while not messages.empty():
            journal.configure(state="normal")
            journal.insert("end", messages.get() + "\n")
            journal.see("end")
            journal.configure(state="disabled")
        window.after(300, pump)

    show_root()
    log("Laisse cette fenêtre ouverte (ou réduite) pendant que tu joues.")
    threading.Thread(target=worker, daemon=True).start()
    if settings.token and settings.game_dir:
        force.set()
        wake.set()
    pump()
    window.mainloop()


def main() -> None:
    threading.Thread(target=remove_old_client, daemon=True).start()
    settings = Settings.load()
    if "--once" in sys.argv:
        Sync(settings, lambda text: print(text, flush=True)).run(force_prices=True)
        return
    run_window(settings)


if __name__ == "__main__":
    main()
