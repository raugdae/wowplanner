"""Connexion au site avec Discord (OAuth2), sans dépendance : cookies signés et appels à l'API Discord.

Déroulé : /auth/login renvoie vers Discord (droit demandé : « identify », le pseudo seulement) ; Discord
revient sur /auth/callback avec un code, échangé contre l'identité du visiteur ; le site vérifie (via le bot)
qu'il est membre du serveur, puis pose un cookie de session signé, valable 30 jours. L'appartenance au
serveur est revérifiée une fois par jour : un membre parti ou exclu perd l'accès sous 24 h.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import aiohttp

SESSION_COOKIE = "wp_session"
STATE_COOKIE = "wp_oauth"
SESSION_SECONDS = 30 * 24 * 3600
STATE_SECONDS = 10 * 60
MEMBER_RECHECK_SECONDS = 24 * 3600

AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
API_URL = "https://discord.com/api/v10"


class OAuthError(Exception):
    """Échec de l'échange avec Discord (code expiré, secret faux, Discord injoignable…)."""


# ------------------------------------------------------------------ cookies signés


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign(payload: dict[str, Any], secret: bytes) -> str:
    """Contenu lisible mais infalsifiable : « données.signature » (HMAC-SHA256)."""
    raw = _b64(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode())
    return f"{raw}.{_b64(hmac.new(secret, raw.encode(), hashlib.sha256).digest())}"


def unsign(value: str | None, secret: bytes, now: float | None = None) -> dict[str, Any] | None:
    """Le contenu si la signature est bonne et que « exp » n'est pas dépassé, sinon None."""
    if not value or "." not in value:
        return None
    raw, sig = value.rsplit(".", 1)
    expected = _b64(hmac.new(secret, raw.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(_unb64(raw))
    except (ValueError, binascii.Error):
        return None
    if not isinstance(payload, dict) or payload.get("exp", 0) < (now if now is not None else time.time()):
        return None
    return payload


def load_secret(path: Path) -> bytes:
    """Clé de signature des cookies, créée au premier lancement et gardée dans le dossier de données
    (les sessions survivent ainsi aux redémarrages). La supprimer déconnecte tout le monde."""
    try:
        return bytes.fromhex(path.read_text().strip())
    except (OSError, ValueError):
        pass
    key = secrets.token_bytes(32)
    path.write_text(key.hex())
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass  # Windows : sans effet, pas grave
    return key


def safe_next(value: str | None) -> str:
    """Page où revenir après connexion : seulement une adresse du site (jamais un autre domaine)."""
    if value and value.startswith("/") and not value.startswith(("//", "/\\")):
        return value
    return "/"


# ------------------------------------------------------------------ Discord


@dataclass
class DiscordOAuth:
    session: aiohttp.ClientSession
    client_id: str
    client_secret: str
    redirect_uri: str
    api_url: str = API_URL  # modifiable pour les tests (faux serveur local)
    timeout: float = 15

    def authorize_url(self, state: str) -> str:
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "scope": "identify",
            "redirect_uri": self.redirect_uri,
            "state": state,
            "prompt": "none",  # pas de nouvelle demande d'autorisation si déjà accordée
        }
        return f"{AUTHORIZE_URL}?{urlencode(params)}"

    async def fetch_user(self, code: str) -> dict[str, Any]:
        """Échange le code contre l'identité du visiteur : {"id": int, "name": str}."""
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
        }
        try:
            async with self.session.post(f"{self.api_url}/oauth2/token", data=data, timeout=timeout) as resp:
                if resp.status != 200:
                    raise OAuthError(f"échange du code refusé par Discord (HTTP {resp.status})")
                token = (await resp.json())["access_token"]
            headers = {"Authorization": f"Bearer {token}"}
            async with self.session.get(f"{self.api_url}/users/@me", headers=headers, timeout=timeout) as resp:
                if resp.status != 200:
                    raise OAuthError(f"identité refusée par Discord (HTTP {resp.status})")
                me = await resp.json()
        except (aiohttp.ClientError, TimeoutError, KeyError, ValueError) as exc:
            raise OAuthError(f"Discord injoignable ou réponse inattendue ({exc})") from exc
        return {"id": int(me["id"]), "name": me.get("global_name") or me.get("username") or "?"}
