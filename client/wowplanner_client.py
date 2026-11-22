"""Client WoW Planner : fait le lien entre l'addon WowPlanner et le site (le jeu ne laisse pas les addons parler au
réseau).

- Installe l'addon dans Interface/AddOns du dossier du jeu choisi.
- Toutes les 20 minutes, télécharge les prix de l'hôtel des ventes et les écrit dans Data.lua (pris par le jeu à la
  connexion ou au /reload : « /wp maj » en jeu).
- Dès que le jeu enregistre ce que l'addon a vu (déconnexion, /reload), envoie l'inventaire, les métiers et les
  recettes au site.

Python 3.10+, sans dépendance (tkinter pour la fenêtre). `--once` : une synchro sans fenêtre (réglages déjà
enregistrés), pour tester ou lancer depuis une tâche planifiée.
"""
from __future__ import annotations

import json
import os
import queue
import re
import shutil
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

VERSION = "1.0.0"
DEFAULT_SERVER = "https://wow.raug-info.ch"
PRICES_EVERY = 20 * 60
WATCH_EVERY = 15
ADDON_NAME = "WowPlanner"
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


def install_addon(root: Path, source: Path | None = None) -> bool:
    """Copie l'addon dans le jeu (sans écraser les prix déjà téléchargés). True si quelque chose a changé."""
    source = source or bundled_addon()
    target = addons_dir(root) / ADDON_NAME
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
    return {"client": VERSION, "characters": out}


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


# ====================================================================== synchro


class Sync:
    """Une passe de synchro : addon, prix (si l'heure est venue), inventaire (si le jeu a enregistré)."""

    def __init__(self, settings: Settings, log: Callable[[str], None]):
        self.settings, self.log = settings, log
        self.last_prices = 0.0

    def root(self) -> Path | None:
        return game_root(self.settings.game_dir) if self.settings.game_dir else None

    def run(self, force_prices: bool = False) -> None:
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
            self.prices(api, root, force_prices)
        self.inventory(api, root)

    def prices(self, api: Api, root: Path, force: bool = False) -> None:
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
        target = addons_dir(root) / ADDON_NAME / "Data.lua"
        tmp = target.with_suffix(".tmp")
        tmp.write_text(lua_prices(data), encoding="utf-8")
        os.replace(tmp, target)
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


# ====================================================================== fenêtre


def run_window(settings: Settings) -> None:
    import tkinter as tk
    from tkinter import filedialog, ttk

    messages: queue.Queue[str] = queue.Queue()
    log = lambda text: messages.put(f"{datetime.now():%H:%M:%S}  {text}")  # noqa: E731
    sync = Sync(settings, log)
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
    window.minsize(560, 420)
    frame = ttk.Frame(window, padding=12)
    frame.pack(fill="both", expand=True)
    frame.columnconfigure(1, weight=1)

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

    ttk.Label(frame, text="Site").grid(row=0, column=0, sticky="w", pady=3)
    ttk.Entry(frame, textvariable=server).grid(row=0, column=1, columnspan=2, sticky="ew", pady=3)
    ttk.Label(frame, text="Jeton").grid(row=1, column=0, sticky="w", pady=3)
    ttk.Entry(frame, textvariable=token, show="•").grid(row=1, column=1, columnspan=2, sticky="ew", pady=3)
    ttk.Label(frame, text="Dossier du jeu").grid(row=2, column=0, sticky="w", pady=3)
    ttk.Entry(frame, textvariable=game).grid(row=2, column=1, sticky="ew", pady=3)
    ttk.Button(frame, text="Parcourir…", command=browse).grid(row=2, column=2, padx=(6, 0), pady=3)
    ttk.Label(frame, textvariable=found, foreground="#666").grid(row=3, column=0, columnspan=3, sticky="w")
    buttons = ttk.Frame(frame)
    buttons.grid(row=4, column=0, columnspan=3, sticky="w", pady=(8, 8))
    ttk.Button(buttons, text="Enregistrer et synchroniser", command=save_and_sync).pack(side="left")
    ttk.Label(buttons, text="  Prix toutes les 20 min · inventaire envoyé après chaque /reload ou déconnexion",
              foreground="#666").pack(side="left")
    journal = tk.Text(frame, height=14, wrap="word", state="disabled")
    journal.grid(row=5, column=0, columnspan=3, sticky="nsew")
    frame.rowconfigure(5, weight=1)

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
    settings = Settings.load()
    if "--once" in sys.argv:
        Sync(settings, lambda text: print(text, flush=True)).run(force_prices=True)
        return
    run_window(settings)


if __name__ == "__main__":
    main()
