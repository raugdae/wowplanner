"""Pages du site pour les membres connectés : sorties (créer, s'inscrire, gérer) et « Mes persos ».

Le site ne parle jamais à Discord lui-même : chaque action passe par le bot (cogs/webbridge.py), qui met à
jour le message de la sortie dans le salon Discord comme le ferait un clic sur ses boutons. Les pages relisent
la base à chaque affichage : ce qui est fait sur Discord y apparaît au rechargement.

Les formulaires sont protégés contre les requêtes venues d'autres sites : cookie de session SameSite=Lax,
jeton par joueur dans chaque formulaire (csrf) et vérification de l'en-tête Origin.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Awaitable, Callable
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from aiohttp import web

from .db import Event, Signup
from .embeds import kind_label
from .gamedata import CLASSES, RACES, class_label, race_label, roles_for
from .roles import LABELS, ROLES
from .web import _VIEWER, CLASS_COLORS, avatar_html, class_span, esc, login_url, page
from .webauth import unsign

if TYPE_CHECKING:
    from .cogs.webbridge import WebBridge
    from .web import WebSite

log = logging.getLogger(__name__)


class ActionError(Exception):
    """Refus à montrer tel quel au joueur (texte façon Discord : **gras**, <t:…> …)."""


@dataclass
class WebUser:
    """Le joueur connecté au site, vu comme un utilisateur Discord par EventsCog.register."""
    id: int
    display_name: str


FLASH_COOKIE = "wp_flash"
FLASH_SECONDS = 120
ROLE_ICONS = {"tank": "🛡️", "heal": "⛑️", "dps": "⚔️"}
# Sorties encore affichées après leur heure de début.
SHOW_STARTED_SECONDS = 3 * 3600
# Places vides affichées par rôle (au-delà, juste le compte : un raid 40 serait interminable).
MAX_EMPTY_SHOWN = 6
# Vérification dans l'armurerie pendant la saisie : par joueur, au plus N demandes par minute.
LOOKUP_PER_MINUTE = 30
DEFAULT_TZ = ZoneInfo("Europe/Paris")

DAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
MONTHS = (
    "janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre",
    "décembre",
)


ACTION_SCRIPT = """
<script>
(() => {
  // Confirmation avant les actions irréversibles.
  document.querySelectorAll("form[data-confirm]").forEach(f => f.addEventListener("submit", e => {
    if (!confirm(f.dataset.confirm)) e.preventDefault();
  }));
  // Pas de double envoi (le bouton est désactivé après le départ du formulaire, pour garder sa valeur).
  document.querySelectorAll("form[method=post]").forEach(f => f.addEventListener("submit", e => {
    if (e.defaultPrevented) return;
    setTimeout(() => f.querySelectorAll("button").forEach(b => b.disabled = true), 0);
  }));
  // Boutons de rôle : seuls ceux que le perso choisi peut tenir restent actifs.
  document.querySelectorAll("form.signup").forEach(f => {
    const pick = f.querySelector("select[name=perso]");
    if (!pick) return;
    const apply = () => {
      const opt = pick.selectedOptions[0];
      const roles = opt ? (opt.dataset.roles || "").split(" ") : [];
      f.querySelectorAll("button[name=role]").forEach(b => {
        b.disabled = b.dataset.full === "1" || !roles.includes(b.value);
      });
    };
    pick.addEventListener("change", apply);
    apply();
  });
  // Choix du rôle préféré : enregistré dès qu'on change la liste.
  document.querySelectorAll("select[data-autosubmit]").forEach(s => s.addEventListener("change", () => s.form.submit()));
})();
</script>
"""

LOOKUP_SCRIPT = """
<script>
(() => {
  const input = document.getElementById("new-name"), out = document.getElementById("lookup");
  const submit = document.getElementById("new-submit"), role = document.getElementById("new-role");
  if (!input || !out) return;
  const strict = input.dataset.armory === "1";
  const allRoles = [...role.options].map(o => [o.value, o.textContent]);
  let timer = null, seq = 0;
  function setRoles(list) {
    const keep = role.value;
    role.innerHTML = "";
    for (const [v, t] of list) { const o = document.createElement("option"); o.value = v; o.textContent = t; role.append(o); }
    if ([...role.options].some(o => o.value === keep)) role.value = keep;
  }
  function show(cls, html) { out.className = "lookup " + cls; out.innerHTML = html; }
  function esc(s) { const d = document.createElement("div"); d.textContent = s == null ? "" : String(s); return d.innerHTML; }
  function render(d) {
    if (d.status === "found") {
      show("ok", `✅ <b>${esc(d.name)}</b> · ${esc(d.class)} ${esc(d.race)}` + (d.level ? ` · niveau ${esc(d.level)}` : ""));
      setRoles([["", "Aucun"], ...d.roles]);
      submit.disabled = false;
    } else {
      setRoles(allRoles);
      submit.disabled = strict || d.status === "invalid" || d.status === "duplicate";
      if (d.status === "not_found") show("bad", `❌ <b>${esc(d.name)}</b> est introuvable dans l'armurerie. Vérifie le prénom et le nom ; l'armurerie ne connaît que les persos niveau 10 ou plus, après une déconnexion (parfois quelques heures de retard).`);
      else if (d.status === "duplicate") show("bad", `Tu as déjà un perso nommé <b>${esc(d.name)}</b>.`);
      else if (d.status === "invalid") show("bad", esc(d.text));
      else if (d.status === "disabled") show("wait", "Armurerie non configurée : précise la classe et la race.");
      else if (d.status === "busy") show("wait", "Doucement 🙂 réessaie dans quelques secondes.");
      else show("bad", "Armurerie injoignable pour l'instant : réessaie dans un moment.");
    }
  }
  input.addEventListener("input", () => {
    clearTimeout(timer);
    const value = input.value.trim(), my = ++seq;
    submit.disabled = strict;
    if (value.length < 3) { show("", ""); setRoles(allRoles); return; }
    show("wait", "🔎 Recherche dans l'armurerie…");
    timer = setTimeout(async () => {
      try {
        const r = await fetch("/api/armurerie?nom=" + encodeURIComponent(value), {headers: {Accept: "application/json"}});
        const d = r.status === 429 ? {status: "busy"} : await r.json();
        if (my === seq) render(d);
      } catch (e) { if (my === seq) render({status: "unreachable"}); }
    }, 450);
  });
})();
</script>
"""


def rich(text: str, tz: ZoneInfo) -> str:
    """Message façon Discord (**gras**, `code`, <t:…>, mentions) → HTML sûr."""
    s = esc(text)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"&lt;t:(\d+)(?::[a-zA-Z])?&gt;", lambda m: esc(when_text(int(m.group(1)), tz)), s)
    s = re.sub(r"&lt;@!?\d+&gt;", "un joueur", s)
    return s.replace("\n", "<br>")


def when_text(ts: int, tz: ZoneInfo, now: datetime | None = None) -> str:
    """« aujourd'hui à 21:00 », « demain à 21:00 », « vendredi 20 novembre à 21:00 »."""
    d = datetime.fromtimestamp(ts, tz)
    today = (now or datetime.now(tz)).astimezone(tz).date()
    if d.date() == today:
        day = "aujourd'hui"
    elif d.date() == today + timedelta(days=1):
        day = "demain"
    else:
        day = f"{DAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]}"
        if d.year != today.year:
            day += f" {d.year}"
    return f"{day} à {d:%H:%M}"


def _int(value: Any, field: str, low: int = 0, high: int = 40) -> int | None:
    """Champ numérique facultatif d'un formulaire."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        number = int(text)
    except ValueError:
        raise ActionError(f"« {field} » doit être un nombre.") from None
    if not low <= number <= high:
        raise ActionError(f"« {field} » doit être entre {low} et {high}.")
    return number


def _date_fr(value: str) -> str:
    """2026-11-20 (champ date du navigateur) → 20/11/2026 (format compris par parse_when)."""
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", value.strip())
    return f"{m.group(3)}/{m.group(2)}/{m.group(1)}" if m else value


class MemberPages:
    def __init__(self, site: WebSite):
        self.site = site
        self._lookup_hits: dict[int, list[float]] = {}

    @property
    def backend(self) -> WebBridge | None:
        return self.site.actions

    @property
    def tz(self) -> ZoneInfo:
        return self.backend.timezone if self.backend is not None else DEFAULT_TZ

    def register(self, router: web.UrlDispatcher) -> None:
        router.add_get("/sorties", self.events_page)
        router.add_post("/sorties", self.create_event)
        router.add_post("/sortie/{id}/inscrire", self.signup)
        router.add_post("/sortie/{id}/quitter", self.leave)
        router.add_post("/sortie/{id}/annuler", self.cancel)
        router.add_post("/sortie/{id}/retirer", self.kick)
        router.add_get("/mes-persos", self.characters_page)
        router.add_post("/mes-persos", self.add_character)
        router.add_post("/mes-persos/{id}/role", self.set_role)
        router.add_post("/mes-persos/{id}/supprimer", self.delete_character)
        router.add_get("/api/armurerie", self.armory_lookup)

    # ============================================================ outils

    @staticmethod
    def _user() -> dict[str, Any] | None:
        viewer = _VIEWER.get()
        return viewer.user if viewer is not None else None

    def _web_user(self) -> WebUser | None:
        user = self._user()
        return WebUser(int(user["id"]), str(user.get("name") or "?")) if user else None

    def csrf_token(self, user_id: int) -> str:
        return hmac.new(self.site._secret, f"csrf:{user_id}".encode(), hashlib.sha256).hexdigest()[:32]

    def _csrf_field(self) -> str:
        user = self._user()
        return f'<input type="hidden" name="csrf" value="{self.csrf_token(int(user["id"]))}">' if user else ""

    @staticmethod
    def _same_origin(request: web.Request) -> bool:
        """Les navigateurs envoient Origin avec chaque formulaire : il doit être ce site (pas « null »)."""
        origin = request.headers.get("Origin")
        return not origin or urlparse(origin).netloc == request.host

    def _set_flash(self, response: web.StreamResponse, text: str, ok: bool) -> None:
        payload = {"t": text[:700], "ok": ok, "exp": time.time() + FLASH_SECONDS}
        self.site._set_cookie(response, FLASH_COOKIE, payload, FLASH_SECONDS)

    def _render(self, request: web.Request, title: str, active: str, body: str, scripts: str = "") -> web.Response:
        """Page avec le message de la dernière action (lu une seule fois)."""
        flash = unsign(request.cookies.get(FLASH_COOKIE), self.site._secret) if self.site._secret else None
        notice = ""
        if flash:
            cls = "flash" if flash.get("ok") else "flash err"
            notice = f'<div class="{cls}" role="status">{rich(str(flash.get("t", "")), self.tz)}</div>'
        response = page(title, active, notice + body, scripts + ACTION_SCRIPT)
        if FLASH_COOKIE in request.cookies:
            response.del_cookie(FLASH_COOKIE, path="/")
        return response

    async def _act(
        self, request: web.Request, back: str, action: Callable[[Any, Any], Awaitable[str]],
    ) -> web.StreamResponse:
        """Exécute une action de formulaire et revient sur la page avec un message (succès ou refus)."""
        user = self._web_user()
        if user is None or self.backend is None:
            raise web.HTTPForbidden(text="Connexion Discord nécessaire pour agir depuis le site.")
        form = await request.post()
        response = self.site._redirect(back)
        if not self._same_origin(request) or not hmac.compare_digest(
            str(form.get("csrf", "")), self.csrf_token(user.id)
        ):
            self._set_flash(response, "Formulaire expiré : recharge la page et recommence.", False)
            return response
        try:
            text, ok = await action(user, form), True
        except ActionError as exc:
            text, ok = str(exc), False
        except Exception:
            log.exception("Action du site en échec (%s)", request.path)
            text, ok = "Erreur inattendue, rien n'a été fait. Réessaie dans un moment.", False
        self._set_flash(response, text, ok)
        return response

    @staticmethod
    def _id(request: web.Request) -> int:
        try:
            return int(request.match_info["id"])
        except ValueError:
            raise web.HTTPNotFound(text="Introuvable.") from None

    # ============================================================ sorties

    async def events_page(self, request: web.Request) -> web.Response:
        site = self.site
        gid = site._scope()
        backend = self.backend
        user = self._web_user()
        events =site.db.upcoming_events(gid, int(time.time()) - SHOW_STARTED_SECONDS)
        mine = site.db.get_characters(user.id) if user else []
        can_act = user is not None and backend is not None

        cards = []
        for ev in events:
            signups = site.db.get_signups(ev.message_id)
            manage = can_act and await backend.can_manage(user.id, ev)  # type: ignore[union-attr]
            cards.append(self._event_card(ev, signups, user.id if user else None, mine, can_act, manage))

        if not can_act:
            viewer = _VIEWER.get()
            if viewer is None:
                note = "Connexion Discord non activée sur ce site : inscriptions et création depuis Discord."
            elif backend is None:
                note = "Actions indisponibles pour l'instant (bot en cours de démarrage ?)."
            else:
                note = f'<a href="{esc(login_url(viewer.path))}">Connecte-toi</a> pour t\'inscrire.'
            create = f'<p class="muted">{note}</p>'
        else:
            create = self._create_form(open_=not events)

        body = f"""
<h1 class="title">Sorties</h1>
<p class="sub">Les sorties du serveur, synchronisées avec le salon Discord : t'inscrire ici ou sur Discord revient au même.</p>
{create}
{"".join(cards) or '<p class="empty">Aucune sortie prévue.</p>'}"""
        return self._render(request, "Sorties", "sorties", body)

    def _create_form(self, open_: bool) -> str:
        backend = self.backend
        assert backend is not None
        channels = backend.event_channels()
        if not channels:
            form = (
                '<p class="muted">Aucun salon de sorties connu : crée la première sortie sur Discord avec '
                "<code>/ajouter event</code> (ou renseigne EVENT_CHANNEL_IDS), le site postera ensuite au même endroit.</p>"
            )
        else:
            today = datetime.now(self.tz).date().isoformat()
            options = "".join(f'<option value="{esc(v)}">{esc(label)}</option>' for v, label in backend.instance_options())
            channel_field = ""
            if len(channels) > 1:
                channel_field = (
                    '<label>Salon Discord<select name="salon" required>'
                    + "".join(f'<option value="{cid}">{esc(name)}</option>' for cid, name in channels)
                    + "</select></label>"
                )
            else:
                channel_field = f'<input type="hidden" name="salon" value="{channels[0][0]}">'
            number = lambda name, label: (  # noqa: E731
                f'<label>{label}<input type="number" name="{name}" min="0" max="40" inputmode="numeric"></label>'
            )
            form = f"""<form method="post" action="/sorties" class="form">{self._csrf_field()}
<label class="wide">Donjon ou raid (ou un nom libre)
<input name="instance" list="instances" required maxlength="100" autocomplete="off" placeholder="Tape pour chercher…"></label>
<datalist id="instances">{options}</datalist>
<label>Date<input type="date" name="date" required min="{today}" value="{today}"></label>
<label>Heure<input type="time" name="heure" required value="21:00"></label>
{channel_field}
{number("joueurs", "Joueurs")}{number("tanks", "Tanks")}{number("heals", "Heals")}{number("dps", "DPS")}
<p class="hint wide">Laisse les nombres vides pour la composition habituelle de l'instance (ex. 1 tank, 1 heal, 3 DPS).</p>
<label class="wide">Description (facultatif)<textarea name="description" maxlength="500"
placeholder="Stuff requis, point de rendez-vous…"></textarea></label>
<div class="wide"><button class="act primary">Créer la sortie et la poster sur Discord</button></div>
</form>"""
        return (
            f'<details class="fold"{" open" if open_ else ""}><summary>➕ Nouvelle sortie</summary>'
            f'<div class="fold-body">{form}</div></details>'
        )

    def _event_card(
        self, ev: Event, signups: list[Signup], me: int | None, mine: list, can_act: bool, manage: bool,
    ) -> str:
        mid = ev.message_id
        my_signup = next((s for s in signups if s.user_id == me), None)
        csrf = self._csrf_field()
        by = f" · organisé par {esc(ev.creator_name)}" if ev.creator_name else ""
        jump = f"https://discord.com/channels/{ev.guild_id}/{ev.channel_id}/{mid}"
        desc = f'<p class="ev-desc">{esc(ev.description)}</p>' if ev.description else ""

        roles_html = []
        for role in ROLES:
            cap = ev.caps[role]
            if cap <= 0:
                continue
            members = [s for s in signups if s.role == role]
            items = []
            for s in members:
                if s.character_name:
                    color = CLASS_COLORS.get(s.character_class or "", "inherit")
                    who = (
                        f'<a href="/perso/{s.character_id}" style="color:{color}">{esc(s.character_name)}</a>'
                        f' <small>{esc(class_label(s.character_class or ""))}'
                        + (f" · {esc(s.display_name)}" if s.display_name else "") + "</small>"
                    )
                else:
                    who = esc(s.display_name or "Joueur")
                kick = ""
                if manage and s.user_id != me:
                    name = s.character_name or s.display_name or "ce joueur"
                    kick = (
                        f'<form method="post" action="/sortie/{mid}/retirer" class="inline" '
                        f'data-confirm="Retirer {esc(name)} de la sortie ?">{csrf}'
                        f'<input type="hidden" name="joueur" value="{s.user_id}">'
                        '<button class="x" title="Retirer de la sortie" aria-label="Retirer">✕</button></form>'
                    )
                items.append(f'<li class="{"me" if s.user_id == me else ""}">{who}{kick}</li>')
            free = cap - len(members)
            if 0 < free <= MAX_EMPTY_SHOWN:
                items += ['<li class="free">—</li>'] * free
            elif free > MAX_EMPTY_SHOWN:
                items.append(f'<li class="free">{free} places libres</li>')
            full = " full" if len(members) >= cap else ""
            roles_html.append(
                f'<div class="ev-role{full}"><h4>{ROLE_ICONS[role]} {LABELS[role]}<span>{len(members)}/{cap}</span></h4>'
                f'<ol>{"".join(items)}</ol></div>'
            )

        actions = ""
        if can_act:
            counts = {r: sum(1 for s in signups if s.role == r) for r in ROLES}
            pick = ""
            if mine:
                current = my_signup.character_id if my_signup else None
                if current is None:
                    current = mine[0].id
                options = "".join(
                    f'<option value="{c.id}" data-roles="{" ".join(roles_for(c.wow_class))}"'
                    f'{" selected" if c.id == current else ""}>{esc(c.name)} — {esc(class_label(c.wow_class))}</option>'
                    for c in mine
                )
                pick = f'<select name="perso" class="pick" aria-label="Perso">{options}</select>'
            buttons = []
            for role in ROLES:
                if ev.caps[role] <= 0:
                    continue
                is_mine = my_signup is not None and my_signup.role == role
                full = counts[role] >= ev.caps[role] and not is_mine
                buttons.append(
                    f'<button name="role" value="{role}" class="act{" on" if is_mine else ""}" data-full="{int(full)}"'
                    f'{" disabled" if full else ""}>{ROLE_ICONS[role]} {LABELS[role]}{" · complet" if full else ""}</button>'
                )
            verb = "Changer :" if my_signup else "M'inscrire :"
            signup_form = (
                f'<form method="post" action="/sortie/{mid}/inscrire" class="signup">{csrf}'
                f'<span class="muted">{verb}</span>{pick}{"".join(buttons)}</form>'
            )
            if not mine:
                signup_form += '<span class="muted">· <a href="/mes-persos">ajoute tes persos</a> pour t\'inscrire avec</span>'
            leave = (
                f'<form method="post" action="/sortie/{mid}/quitter">{csrf}<button class="act">Me désinscrire</button></form>'
                if my_signup else ""
            )
            cancel = (
                f'<form method="post" action="/sortie/{mid}/annuler" data-confirm="Annuler {esc(ev.instance)} ? '
                f'Les inscrits seront prévenus sur Discord.">{csrf}<button class="act danger">Annuler la sortie</button></form>'
                if manage else ""
            )
            actions = f'<div class="ev-actions">{signup_form}{leave}{cancel}</div>'

        return f"""<article class="ev card{" mine" if my_signup else ""}" id="s{mid}">
<div class="ev-head"><div><h3>{esc(ev.instance)}</h3>
<div class="muted"><span class="ev-when">📅 {esc(when_text(ev.starts_at, self.tz))}</span> · {esc(kind_label(ev))}{by}
 · {len(signups)}/{ev.size} inscrit(s)</div></div>
<a class="muted" href="{esc(jump)}" target="_blank" rel="noopener noreferrer">Voir sur Discord ↗</a></div>
{desc}<div class="ev-roles">{"".join(roles_html)}</div>{actions}</article>"""

    async def create_event(self, request: web.Request) -> web.StreamResponse:
        async def action(user, form) -> str:
            channel = form.get("salon")
            return await self.backend.create_event(  # type: ignore[union-attr]
                user,
                int(channel) if str(channel or "").isdigit() else None,
                str(form.get("instance", "")).strip()[:100],
                _date_fr(str(form.get("date", ""))),
                str(form.get("heure", "")),
                _int(form.get("joueurs"), "Joueurs", 1),
                _int(form.get("tanks"), "Tanks"),
                _int(form.get("heals"), "Heals"),
                _int(form.get("dps"), "DPS"),
                str(form.get("description", "")).strip()[:500] or None,
            )

        return await self._act(request, "/sorties", action)

    async def signup(self, request: web.Request) -> web.StreamResponse:
        mid = self._id(request)

        async def action(user, form) -> str:
            perso = str(form.get("perso") or "")
            return await self.backend.signup(  # type: ignore[union-attr]
                user, mid, str(form.get("role", "")), int(perso) if perso.isdigit() else None
            )

        return await self._act(request, f"/sorties#s{mid}", action)

    async def leave(self, request: web.Request) -> web.StreamResponse:
        mid = self._id(request)
        return await self._act(request, f"/sorties#s{mid}", lambda user, form: self.backend.leave(user, mid))

    async def cancel(self, request: web.Request) -> web.StreamResponse:
        mid = self._id(request)
        return await self._act(request, "/sorties", lambda user, form: self.backend.cancel(user, mid))

    async def kick(self, request: web.Request) -> web.StreamResponse:
        mid = self._id(request)

        async def action(user, form) -> str:
            target = str(form.get("joueur") or "")
            return await self.backend.kick(user, mid, int(target) if target.isdigit() else 0)  # type: ignore[union-attr]

        return await self._act(request, f"/sorties#s{mid}", action)

    # ============================================================ mes persos

    async def characters_page(self, request: web.Request) -> web.Response:
        user = self._web_user()
        backend = self.backend
        if user is None or backend is None:
            body = (
                '<h1 class="title">Mes persos</h1><p class="muted">Connexion Discord nécessaire pour gérer tes persos '
                "depuis le site (sinon : <code>/ajouter perso</code> sur Discord).</p>"
            )
            return self._render(request, "Mes persos", "mes-persos", body)
        csrf = self._csrf_field()
        mine = self.site.db.get_characters(user.id)
        rows = []
        for c in mine:
            choices = [("", "Aucun")] + [(r, LABELS[r]) for r in roles_for(c.wow_class)]
            select = "".join(
                f'<option value="{v}"{" selected" if (c.preferred_role or "") == v else ""}>{esc(t)}</option>'
                for v, t in choices
            )
            role_form = (
                f'<form method="post" action="/mes-persos/{c.id}/role" class="inline">{csrf}'
                f'<select name="role" class="pick" data-autosubmit aria-label="Rôle préféré">{select}</select>'
                '<noscript><button class="act">OK</button></noscript></form>'
            )
            delete = (
                f'<form method="post" action="/mes-persos/{c.id}/supprimer" class="inline" '
                f'data-confirm="Supprimer {esc(c.name)} (et ses métiers) ? Ses inscriptions aux sorties restent, sans le perso.">'
                f'{csrf}<button class="act danger">Supprimer</button></form>'
            )
            origin = '<span class="src-tag">site</span>' if c.source == "web" else '<span class="src-tag">Discord</span>'
            if c.armory_synced_at is None and c.source != "web":
                origin += ' <span class="src-tag" title="Retiré automatiquement s\'il reste introuvable">⚠️ pas dans l\'armurerie</span>'
            rows.append(
                f'<tr><td><a class="who-cell" href="/perso/{c.id}">{avatar_html(c)}<b>{esc(c.name)}</b></a></td>'
                f'<td class="num">{c.level or ""}</td><td>{class_span(c)}</td><td>{esc(race_label(c.race))}</td>'
                f"<td>{role_form}</td><td>{origin}</td><td>{delete}</td></tr>"
            )
        table = (
            '<div class="table-wrap"><table><thead><tr><th>Perso</th><th class="num">Niv.</th><th>Classe</th>'
            f'<th>Race</th><th>Rôle préféré</th><th>Ajouté sur</th><th></th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
            if rows else '<p class="empty">Aucun perso pour l\'instant : ajoute le premier ci-dessous.</p>'
        )

        strict = backend.armory_enabled
        manual = ""
        if not strict:
            classes = "".join(f'<option value="{k}">{esc(v[0])}</option>' for k, v in CLASSES.items())
            races = "".join(f'<option value="{k}">{esc(v[0])}</option>' for k, v in RACES.items())
            manual = (
                f'<label>Classe<select name="classe" required>{classes}</select></label>'
                f'<label>Race<select name="race" required>{races}</select></label>'
            )
        roles = '<option value="">Aucun</option>' + "".join(f'<option value="{r}">{LABELS[r]}</option>' for r in ROLES)
        help_text = (
            "Tape le nom exact du perso (prénom et nom) : il est vérifié dans l'armurerie pendant la saisie, et "
            "sa classe, sa race et son niveau en sont repris."
            if strict else "Armurerie non configurée : précise la classe et la race."
        )
        add = f"""<form method="post" action="/mes-persos" class="form" autocomplete="off">{csrf}
<label class="wide">Nom du perso<input id="new-name" name="nom" required minlength="2" maxlength="32"
placeholder="Prénom Nom (ex. Grommash Hurlenfer)" data-armory="{int(strict)}"></label>
<div id="lookup" class="lookup wide" aria-live="polite"></div>
{manual}
<label>Rôle préféré<select id="new-role" name="role">{roles}</select></label>
<div><button id="new-submit" class="act primary"{" disabled" if strict else ""}>Ajouter</button></div>
<p class="hint wide">{help_text}</p>
</form>"""
        body = f"""
<h1 class="title">Mes persos</h1>
<p class="sub">Tes persos, ceux déclarés ici comme ceux déclarés sur Discord avec <code>/ajouter perso</code>.
Ceux de Discord encore introuvables dans l'armurerie au bout de 2 jours sont retirés chaque nuit.</p>
{table}
<h2>Ajouter un perso</h2>
{add}"""
        return self._render(request, "Mes persos", "mes-persos", body, LOOKUP_SCRIPT)

    async def add_character(self, request: web.Request) -> web.StreamResponse:
        async def action(user, form) -> str:
            return await self.backend.add_character(  # type: ignore[union-attr]
                user, str(form.get("nom", "")), str(form.get("role") or "") or None,
                str(form.get("classe") or "") or None, str(form.get("race") or "") or None,
            )

        return await self._act(request, "/mes-persos", action)

    async def set_role(self, request: web.Request) -> web.StreamResponse:
        cid = self._id(request)

        async def action(user, form) -> str:
            role = str(form.get("role") or "")
            return await self.backend.set_role(user, cid, role or None)  # type: ignore[union-attr]

        return await self._act(request, "/mes-persos", action)

    async def delete_character(self, request: web.Request) -> web.StreamResponse:
        cid = self._id(request)
        return await self._act(request, "/mes-persos", lambda user, form: self.backend.delete_character(user, cid))

    async def armory_lookup(self, request: web.Request) -> web.Response:
        user = self._web_user()
        if user is None or self.backend is None:
            return web.json_response({"status": "unreachable"}, status=403)
        now = time.monotonic()
        hits = [t for t in self._lookup_hits.get(user.id, []) if now - t < 60]
        if len(hits) >= LOOKUP_PER_MINUTE:
            return web.json_response({"status": "busy"}, status=429)
        hits.append(now)
        self._lookup_hits[user.id] = hits
        result = await self.backend.armory_lookup(user.id, request.query.get("nom", "")[:40])
        return web.json_response(result)
