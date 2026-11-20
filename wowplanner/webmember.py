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

from .cogs.armory import PURGE_GRACE_DAYS
from .db import SOURCE_WEB, Character, Event, Signup
from .embeds import kind_label
from .gamedata import CLASSES, RACES, class_label, race_label, roles_for
from .orders import MAX_QUANTITY, STATUS_LABELS, TRANSITIONS, allowed_actions
from .orders import search as order_search
from .recipes import normalize
from .roles import LABELS, ROLES
from .webrecipes import recipe_card
from .webui import (
    _VIEWER, CLASS_COLORS, FILTER_SCRIPT, QUALITY_COLORS, avatar_html, class_span, esc, login_url, page,
)
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
  const owner = document.getElementById("new-owner");  // formulaire d'admin : perso pour un autre membre
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
      else if (d.status === "duplicate") show("bad", (owner ? "Ce membre a" : "Tu as") + ` déjà un perso nommé <b>${esc(d.name)}</b>.`);
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
        const forWhom = owner && owner.value ? "&pour=" + encodeURIComponent(owner.value) : "";
        const r = await fetch("/api/armurerie?nom=" + encodeURIComponent(value) + forWhom, {headers: {Accept: "application/json"}});
        const d = r.status === 429 ? {status: "busy"} : await r.json();
        if (my === seq) render(d);
      } catch (e) { if (my === seq) render({status: "unreachable"}); }
    }, 450);
  });
  if (owner) owner.addEventListener("change", () => input.dispatchEvent(new Event("input")));
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


def source_tags(c: Character, tz: ZoneInfo = DEFAULT_TZ) -> str:
    """Où le perso a été ajouté, et s'il risque le nettoyage de nuit (Discord, absent de l'armurerie)."""
    if c.source == SOURCE_WEB:
        return '<span class="src-tag">site</span>'
    tag = '<span class="src-tag">Discord</span>'
    if c.armory_synced_at is None:
        when = ""
        if c.created_at:
            limit = datetime.fromtimestamp(c.created_at + PURGE_GRACE_DAYS * 86400, tz)
            when = f", retiré vers le {limit:%d/%m} s'il reste introuvable"
        tag += f' <span class="src-tag warn" title="Pas trouvé dans l\'armurerie{when}">⚠️ pas dans l\'armurerie{when}</span>'
    return tag


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
        router.add_post("/mes-persos/{id}/favori", self.set_favorite)
        router.add_get("/api/armurerie", self.armory_lookup)
        router.add_get("/atelier", self.atelier_page)
        router.add_post("/atelier/commander", self.place_order)
        router.add_post("/atelier/{id}/{action}", self.order_action)
        router.add_get("/admin", self.admin_page)
        router.add_post("/admin/sync", self.admin_sync)
        router.add_post("/admin/persos", self.admin_add_character)
        router.add_post("/admin/persos/{id}/role", self.admin_set_role)
        router.add_post("/admin/persos/{id}/supprimer", self.admin_delete_character)

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
            # Lien « Créer une sortie » d'une fiche de donjon : formulaire ouvert et prérempli.
            preset = {k: request.query.get(k, "")[:100] for k in ("instance", "joueurs")}
            create = self._create_form(open_=not events or bool(preset["instance"]), preset=preset)

        body = f"""
<h1 class="title">Sorties</h1>
<p class="sub">Les sorties du serveur, synchronisées avec le salon Discord : t'inscrire ici ou sur Discord revient au même.</p>
{create}
{"".join(cards) or '<p class="empty">Aucune sortie prévue.</p>'}"""
        return self._render(request, "Sorties", "sorties", body)

    def _create_form(self, open_: bool, preset: dict[str, str] | None = None) -> str:
        preset = preset or {}
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
                f'<label>{label}<input type="number" name="{name}" min="0" max="40" inputmode="numeric"'
                f' value="{esc(preset.get(name, "")) if preset.get(name, "").isdigit() else ""}"></label>'
            )
            form = f"""<form method="post" action="/sorties" class="form">{self._csrf_field()}
<label class="wide">Donjon ou raid (ou un nom libre)
<input name="instance" list="instances" required maxlength="100" autocomplete="off" placeholder="Tape pour chercher…"
value="{esc(preset.get("instance", ""))}"></label>
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
            f'<details class="fold" id="nouvelle"{" open" if open_ else ""}><summary>➕ Nouvelle sortie</summary>'
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
                # Perso déjà inscrit, sinon le perso préféré (en tête de liste), sinon le premier.
                ordered = sorted(mine, key=lambda c: not c.favorite)
                current = my_signup.character_id if my_signup else None
                if current is None:
                    current = ordered[0].id
                options = "".join(
                    f'<option value="{c.id}" data-roles="{" ".join(roles_for(c.wow_class))}"'
                    f'{" selected" if c.id == current else ""}>{"⭐ " if c.favorite else ""}{esc(c.name)} — '
                    f"{esc(class_label(c.wow_class))}</option>"
                    for c in ordered
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
            origin = source_tags(c)
            title = "Ne plus en faire mon perso préféré" if c.favorite else "En faire mon perso préféré"
            star = (
                f'<form method="post" action="/mes-persos/{c.id}/favori" class="inline">{csrf}'
                f'<button class="fav{" on" if c.favorite else ""}" title="{title}" aria-label="{title}" '
                f'aria-pressed="{"true" if c.favorite else "false"}">{"★" if c.favorite else "☆"}</button></form>'
            )
            rows.append(
                f'<tr><td>{star}</td><td><a class="who-cell" href="/perso/{c.id}">{avatar_html(c)}<b>{esc(c.name)}</b></a></td>'
                f'<td class="num">{c.level or ""}</td><td>{class_span(c)}</td><td>{esc(race_label(c.race))}</td>'
                f"<td>{role_form}</td><td>{origin}</td><td>{delete}</td></tr>"
            )
        table = (
            '<div class="table-wrap"><table><thead><tr><th title="Perso préféré">★</th><th>Perso</th>'
            '<th class="num">Niv.</th><th>Classe</th>'
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
☆ : choisis ton perso préféré, proposé en premier pour t'inscrire aux sorties (sur le site comme sur Discord).
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

    # ============================================================ atelier

    async def atelier_page(self, request: web.Request) -> web.Response:
        user = self._web_user()
        backend = self.backend
        if user is None or backend is None:
            body = (
                '<h1 class="title">Atelier</h1><p class="muted">Connexion Discord nécessaire pour commander depuis le '
                "site (sinon : le panneau de l'atelier sur Discord, ou <code>/commander</code>).</p>"
            )
            return self._render(request, "Atelier", "atelier", body)
        csrf = self._csrf_field()
        tz = self.tz
        candidates = backend.orderable(user.id)
        query = request.query.get("q", "").strip()[:80]

        # --- Formulaire de commande d'une recette (lien « Commander » d'une recette ou d'un objet conseillé)
        order_form = ""
        wanted = request.query.get("recette", "")
        if wanted.isdigit():
            candidate = next((c for c in candidates if c.recipe.id == int(wanted)), None)
            if candidate is None:
                order_form = (
                    '<div class="flash err">Personne d\'autre que toi ne sait fabriquer cet objet sur le serveur '
                    "(seules les recettes vues dans l'armurerie comptent).</div>"
                )
            else:
                recipe = candidate.recipe
                crafters = "".join(
                    f'<option value="{c.character_id}">{esc(c.name)} — {esc(class_label(c.wow_class))}</option>'
                    for c in candidate.crafters
                )
                order_form = f"""<section class="card admin-sec" id="commande"><h2>🛒 Commander : {esc(recipe.name)}</h2>
<div class="order-grid"><div class="cards">{recipe_card(recipe, backend.crafted_by(), None, order_link=False)}</div>
<form method="post" action="/atelier/commander" class="form">{csrf}
<input type="hidden" name="recette" value="{recipe.id}">
<label>Artisan<select name="artisan" required>{crafters}</select></label>
<label>Quantité<input type="number" name="quantite" min="1" max="{MAX_QUANTITY}" value="1" required></label>
<label class="wide">Un mot pour l'artisan (facultatif)<textarea name="note" maxlength="300"
placeholder="J'ai les composants, je te les envoie par courrier…"></textarea></label>
<div class="wide"><button class="act primary">📨 Envoyer la commande</button></div>
<p class="hint wide">L'artisan la reçoit en MP sur Discord, avec les boutons Accepter / Refuser, et la retrouve ici.
Composants et livraison se règlent entre vous en jeu (courrier, échange).</p>
</form></div></section>"""

        # --- Recherche
        results = ""
        if query:
            found = order_search(candidates, query)[:60]
            rows = "".join(
                f'<tr><td><b style="color:{QUALITY_COLORS.get((c.recipe.item or {}).get("quality") or "", "inherit")}">'
                f"{esc(c.recipe.name)}</b></td><td>{esc(', '.join(x.name for x in c.crafters))}</td>"
                f'<td><a class="order-link" href="/atelier?recette={c.recipe.id}#commande">🛒 Commander</a></td></tr>'
                for c in found
            )
            results = (
                '<div class="table-wrap"><table><thead><tr><th>Objet</th><th>Artisans</th><th></th></tr></thead>'
                f"<tbody>{rows}</tbody></table></div>"
                if rows else f'<p class="empty">Rien ne correspond à « {esc(query)} » parmi les recettes des autres joueurs.</p>'
            )
        search_form = f"""<form method="get" action="/atelier" class="filters">
<input type="search" name="q" value="{esc(query)}" placeholder="Quel objet ? (un bout suffit, ex. mangouste, sac en lin…)"
autocomplete="off"><button class="act primary">Chercher</button></form>
<p class="muted">{len(candidates)} recette(s) commandable(s) : celles que les persos des autres joueurs ont débloquées
(vues dans l'armurerie). Tu peux aussi commander depuis la page <a href="/metiers">Métiers</a> ou l'équipement
conseillé d'une fiche perso.</p>"""

        # --- Mes commandes
        orders = backend.user_orders(user.id)

        def order_rows(items: list, received: bool) -> str:
            rows = []
            for o in items:
                buttons = "".join(
                    f'<form method="post" action="/atelier/{o.id}/{a}" class="inline"'
                    + (f' data-confirm="{esc(TRANSITIONS[a].label)} la commande #{o.id} ?"' if a in ("refuse", "drop", "cancel") else "")
                    + f'>{csrf}<button class="act{" danger" if a in ("refuse", "drop", "cancel") else " primary"}">'
                    f"{TRANSITIONS[a].emoji} {esc(TRANSITIONS[a].label)}</button></form>"
                    for a in allowed_actions(o, user.id)
                )
                other = f"pour {esc(o.requester_name)} ({esc(o.crafter_name)})" if received else f"chez {esc(o.crafter_name)}"
                note = f'<div class="muted">💬 « {esc(o.note)} »</div>' if o.note else ""
                reagents = f'<details><summary class="muted">Composants</summary><pre class="reagents">{esc(o.reagents_text or "—")}</pre></details>'
                rows.append(
                    f"<tr><td>#{o.id}</td><td><b>{o.quantity}× {esc(o.recipe_name)}</b>{note}{reagents}</td>"
                    f"<td>{other}</td><td>{esc(STATUS_LABELS.get(o.status, o.status))}<div class=\"muted\">"
                    f"{esc(when_text(o.updated_at, tz))}</div></td><td><div class=\"ev-actions\">{buttons}</div></td></tr>"
                )
            head = "<tr><th>#</th><th>Objet</th><th>" + ("Client" if received else "Artisan") + "</th><th>Statut</th><th></th></tr>"
            return f'<div class="table-wrap"><table><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table></div>'

        received = [o for o in orders if o.crafter_user_id == user.id]
        placed = [o for o in orders if o.requester_id == user.id]
        mine = ""
        if received:
            mine += f"<h3>📥 On t'a demandé</h3>{order_rows(received, True)}"
        if placed:
            mine += f"<h3>📤 Tu as commandé</h3>{order_rows(placed, False)}"
        if not orders:
            mine = '<p class="empty">Aucune commande pour l\'instant.</p>'

        body = f"""
<h1 class="title">Atelier</h1>
<p class="sub">Commande un objet à un perso du serveur qui sait le fabriquer. Synchronisé avec l'atelier de Discord :
l'artisan reçoit la commande en MP, et chacun peut répondre ici ou sur Discord.</p>
{order_form}
<h2>🛒 Commander un objet</h2>
{search_form}
{results}
<h2>📦 Mes commandes</h2>
<p class="muted">Les commandes en cours, puis les dernières terminées.</p>
{mine}"""
        return self._render(request, "Atelier", "atelier", body)

    async def place_order(self, request: web.Request) -> web.StreamResponse:
        async def action(user, form) -> str:
            recipe, crafter = str(form.get("recette") or ""), str(form.get("artisan") or "")
            if not recipe.isdigit() or not crafter.isdigit():
                raise ActionError("Choisis l'objet et l'artisan.")
            quantity = _int(form.get("quantite"), "Quantité", 1, MAX_QUANTITY) or 1
            note = str(form.get("note") or "").strip()[:300] or None
            return await self.backend.place_order(user, int(recipe), int(crafter), quantity, note)  # type: ignore[union-attr]

        return await self._act(request, "/atelier", action)

    async def order_action(self, request: web.Request) -> web.StreamResponse:
        order_id = self._id(request)
        action = request.match_info["action"]
        return await self._act(
            request, "/atelier", lambda user, form: self.backend.order_action(user, order_id, action)
        )

    async def set_favorite(self, request: web.Request) -> web.StreamResponse:
        cid = self._id(request)
        return await self._act(request, "/mes-persos", lambda user, form: self.backend.set_favorite(user, cid))

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
        # « pour » : formulaire d'admin, les doublons sont cherchés chez le membre choisi.
        owner = user.id
        target = request.query.get("pour", "")
        if target.isdigit() and int(target) != user.id and await self.backend.is_admin(user.id):
            owner = int(target)
        result = await self.backend.armory_lookup(owner, request.query.get("nom", "")[:40])
        return web.json_response(result)

    # ============================================================ administration

    async def _admin_user(self) -> WebUser | None:
        user = self._web_user()
        if user is None or self.backend is None or not await self.backend.is_admin(user.id):
            return None
        return user

    async def admin_page(self, request: web.Request) -> web.Response:
        user = await self._admin_user()
        if user is None:
            body = (
                '<h1 class="title">Administration</h1><p class="muted">Réservé aux membres qui ont la permission '
                "« Gérer le serveur » sur Discord.</p>"
            )
            response = self._render(request, "Administration", "", body)
            response.set_status(403)
            return response
        backend = self.backend
        assert backend is not None
        site = self.site
        gid = site._scope()
        csrf = self._csrf_field()
        tz = self.tz

        # --- Synchro
        state = backend.sync_state
        last = backend.last_sync()
        last_text = (
            f"Dernière synchro terminée {esc(when_text(int(last), tz))}." if last else "Aucune synchro enregistrée."
        )
        sync_lines = ""
        running = bool(state and state.get("running"))
        if state:
            started = esc(when_text(int(state["started"]), tz))
            head = (
                f"⏳ Synchro en cours (lancée par {esc(state['by'])} {started})…" if running
                else f"Dernière synchro lancée depuis le site par {esc(state['by'])} {started} :"
            )
            items = "".join(f"<li>{rich(line, tz)}</li>" for line in state.get("lines") or [])
            sync_lines = f'<div class="sync-log"><p>{head}</p><ul>{items}</ul></div>'
        sync_html = f"""<section class="card admin-sec"><h2>🔄 Synchro des données</h2>
<p class="muted">Comme <code>/admin sync</code> : donjons, priorités de stats, talents, tous les persos (armurerie),
nettoyage des persos Discord introuvables et toutes les recettes. Elle tourne aussi chaque nuit à 4 h. {last_text}</p>
{sync_lines}
<form method="post" action="/admin/sync" data-confirm="Lancer la synchro complète maintenant ? Elle peut prendre plusieurs minutes.">
{csrf}<button class="act primary"{" disabled" if running else ""}>Lancer la synchro complète</button></form></section>"""

        # --- Persos des membres
        characters = sorted(site.db.guild_characters(gid), key=lambda c: c.name.lower())
        member_ids = site.db.guild_member_ids(gid)
        names = await backend.member_names(sorted({c.user_id for c in characters} | set(member_ids)))
        rows = []
        for c in characters:
            owner = names.get(c.user_id, "?")
            choices = [("", "Aucun")] + [(r, LABELS[r]) for r in roles_for(c.wow_class)]
            select = "".join(
                f'<option value="{v}"{" selected" if (c.preferred_role or "") == v else ""}>{esc(t)}</option>'
                for v, t in choices
            )
            search = normalize(" ".join([c.name, owner, class_label(c.wow_class)]))
            rows.append(
                f'<tr data-search="{esc(search)}"><td><a class="who-cell" href="/perso/{c.id}">{avatar_html(c)}'
                f'<b>{esc(c.name)}</b></a></td><td>{esc(owner)}</td><td class="num">{c.level or ""}</td>'
                f"<td>{class_span(c)}</td>"
                f'<td><form method="post" action="/admin/persos/{c.id}/role" class="inline">{csrf}'
                f'<select name="role" class="pick" data-autosubmit aria-label="Rôle préféré">{select}</select>'
                '<noscript><button class="act">OK</button></noscript></form></td>'
                f"<td>{source_tags(c, tz)}</td>"
                f'<td><form method="post" action="/admin/persos/{c.id}/supprimer" class="inline" '
                f'data-confirm="Supprimer {esc(c.name)} ({esc(owner)}) ? Le joueur est prévenu en MP.">{csrf}'
                '<button class="act danger">Supprimer</button></form></td></tr>'
            )
        table = (
            '<div class="filters"><input id="q" type="search" placeholder="Chercher un perso, un joueur, une classe…" '
            'autocomplete="off"></div><div class="table-wrap"><table><thead><tr><th>Perso</th><th>Joueur</th>'
            '<th class="num">Niv.</th><th>Classe</th><th>Rôle préféré</th><th>Origine</th><th></th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>'
            if rows else '<p class="empty">Aucun perso déclaré.</p>'
        )
        missing = sum(1 for c in characters if c.source != SOURCE_WEB and c.armory_synced_at is None)
        missing_text = (
            f" {missing} perso(s) ajouté(s) sur Discord ne sont pas dans l'armurerie (⚠️) : retirés par la synchro de nuit "
            f"{PURGE_GRACE_DAYS} jours après leur ajout s'ils restent introuvables." if missing else ""
        )

        # --- Ajouter un perso à un membre
        members = sorted(member_ids, key=lambda uid: names.get(uid, "").lower())
        member_options = "".join(f'<option value="{uid}">{esc(names.get(uid, str(uid)))}</option>' for uid in members)
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
        add = f"""<form method="post" action="/admin/persos" class="form" autocomplete="off">{csrf}
<label>Membre<select id="new-owner" name="membre" required><option value="">Choisis…</option>{member_options}</select></label>
<label class="wide">Nom du perso<input id="new-name" name="nom" required minlength="2" maxlength="32"
placeholder="Prénom Nom (ex. Grommash Hurlenfer)" data-armory="{int(strict)}"></label>
<div id="lookup" class="lookup wide" aria-live="polite"></div>
{manual}
<label>Rôle préféré<select id="new-role" name="role">{roles}</select></label>
<div><button id="new-submit" class="act primary"{" disabled" if strict else ""}>Ajouter pour ce membre</button></div>
<p class="hint wide">Comme <code>/admin ajouter perso</code> : le membre est prévenu en MP. La liste montre les membres
déjà vus par le bot (inscrits à une sortie, persos déclarés, connectés au site).</p>
</form>"""

        body = f"""
<h1 class="title">Administration</h1>
<p class="sub">Les outils de <code>/admin</code>, pour les membres qui ont la permission « Gérer le serveur » sur Discord.</p>
{sync_html}
<section class="card admin-sec" id="persos"><h2>👥 Persos des membres</h2>
<p class="muted">{len(characters)} perso(s). Modifier le rôle préféré ou supprimer un perso (son joueur est prévenu en MP
quand c'est un autre que toi).{missing_text}</p>
{table}
<h2>➕ Ajouter un perso à un membre</h2>
{add}</section>
<section class="card admin-sec"><h2>📅 Sorties</h2>
<p class="muted">Sur la page <a href="/sorties">Sorties</a>, tu peux annuler n'importe quelle sortie (les inscrits sont
prévenus sur Discord) et retirer un inscrit, comme <code>/supprimer event</code> et <code>/supprimer inscrit</code>.</p>
</section>
<section class="card admin-sec"><h2>🔨 Atelier</h2>
<p class="muted">Le panneau de l'atelier se poste depuis Discord, dans le salon voulu : <code>/admin atelier</code>.</p>
</section>"""
        return self._render(request, "Administration", "", body, LOOKUP_SCRIPT + FILTER_SCRIPT)

    async def admin_sync(self, request: web.Request) -> web.StreamResponse:
        return await self._act(request, "/admin", lambda user, form: self.backend.start_sync(user))

    async def admin_add_character(self, request: web.Request) -> web.StreamResponse:
        async def action(user, form) -> str:
            owner = str(form.get("membre") or "")
            if not owner.isdigit():
                raise ActionError("Choisis le membre à qui appartient le perso.")
            return await self.backend.add_character(  # type: ignore[union-attr]
                user, str(form.get("nom", "")), str(form.get("role") or "") or None,
                str(form.get("classe") or "") or None, str(form.get("race") or "") or None, owner_id=int(owner),
            )

        return await self._act(request, "/admin#persos", action)

    async def admin_set_role(self, request: web.Request) -> web.StreamResponse:
        cid = self._id(request)

        async def action(user, form) -> str:
            role = str(form.get("role") or "")
            return await self.backend.set_role(user, cid, role or None)  # type: ignore[union-attr]

        return await self._act(request, "/admin#persos", action)

    async def admin_delete_character(self, request: web.Request) -> web.StreamResponse:
        cid = self._id(request)
        return await self._act(request, "/admin#persos", lambda user, form: self.backend.delete_character(user, cid))
