# WoW Planner

Bot Discord pour organiser des sorties donjon / raid sur **World of Warcraft: Forever**.

- `/event creer` publie un message de sortie : instance, date, nombre de joueurs et places par rôle.
- Les joueurs s'inscrivent en réagissant : 🛡️ Tank, ⛑️ Heal, ⚔️ DPS.
- Quand un rôle est complet, il est verrouillé : le bot retire son émote, refuse les nouvelles réactions sur ce rôle et prévient le joueur par MP.
- Toute autre émote ajoutée au message est retirée automatiquement.
- La liste des donjons et raids vient de [warcraft.wiki.gg](https://warcraft.wiki.gg/wiki/World_of_Warcraft:_Forever) et se met à jour toute seule une fois par jour.

## Commandes

| Commande | Rôle |
|---|---|
| `/event creer instance date heure [joueurs] [tanks] [heals] [dps] [description]` | Crée une sortie. L'instance se cherche par nom ou abréviation (`brd`, `ony`, `sm cath`…). |
| `/event liste` | Prochaines sorties du serveur. |
| `/event annuler sortie` | Annule la sortie, prévient les inscrits. Réservé à l'organisateur et aux modérateurs. |
| `/event retirer sortie joueur` | Désinscrit un joueur. Réservé à l'organisateur et aux modérateurs. |
| `/instances liste [type]` | Affiche les donjons (avec niveaux) et les raids. |
| `/instances maj` | Force la mise à jour depuis le wiki (permission « Gérer le serveur »). |

**Date** : `25/12/2026`, `25/12`, `aujourd'hui`, `demain`. **Heure** : `21:00`, `21h30`, `21h`.

**Composition** : si tu ne précises rien, le bot utilise la taille de l'instance avec une répartition classique :

| Taille | Tank | Heal | DPS |
|---|---|---|---|
| 5 (donjon) | 1 | 1 | 3 |
| 10 | 2 | 3 | 5 |
| 20 | 3 | 5 | 12 |
| 40 | 4 | 10 | 26 |

Tu peux surcharger n'importe quel rôle. Exemple : `tanks:2` sur Hyjal Summit garde 5 heals, et les DPS remplissent le reste (13). Un nom d'instance libre est accepté si tu donnes `joueurs` ou les trois rôles.

### Règles d'inscription

- Le message affiche le pseudo des inscrits sous chaque rôle, dans l'ordre d'inscription, avec les places restantes.
- Un seul rôle par joueur. Réagir sur un autre rôle te déplace, s'il reste de la place.
- Retirer ta réaction te désinscrit.
- Discord ne permet pas d'interdire une émote précise sur un message. Le « blocage » fonctionne donc ainsi : le bot retire sa propre réaction du rôle complet, puis supprime aussitôt toute nouvelle réaction sur ce rôle. Dès qu'une place se libère, il remet son émote.
- Si le bot redémarre, il resynchronise les sorties à venir avec les réactions présentes sur les messages.

## Installation

### 1. Créer le bot sur Discord

1. Ouvre <https://discord.com/developers/applications> et clique sur **New Application**.
2. Dans l'onglet **Bot**, clique sur **Reset Token** et copie le token. Aucun *Privileged Gateway Intent* n'est nécessaire.
3. Dans l'onglet **OAuth2 → URL Generator**, coche les scopes `bot` et `applications.commands`, puis ces permissions :
   View Channel, Send Messages, Embed Links, Add Reactions, **Manage Messages** (pour retirer les réactions refusées), Read Message History.
   Tu peux aussi utiliser directement le lien suivant, en remplaçant `CLIENT_ID` :
   `https://discord.com/oauth2/authorize?client_id=CLIENT_ID&scope=bot+applications.commands&permissions=93248`
4. Ouvre le lien et invite le bot sur ton serveur.

### 2. Configurer

```bash
cp .env.example .env
# puis renseigne DISCORD_TOKEN, et GUILD_ID pour que les commandes apparaissent tout de suite
```

Pour utiliser des émotes du serveur à la place des émotes par défaut : `EMOJI_TANK=<:tank:123456789012345678>`. Pour trouver l'ID d'une émote, tape `\:tank:` dans Discord.

### 3. Configurer le salon des sorties

L'objectif est que, dans ce salon, les joueurs ne puissent que lancer les commandes et réagir avec les 3 émotes. Ça se règle dans Discord : **Modifier le salon → Permissions**.

**@everyone** :

| Permission | Réglage | Pourquoi |
|---|---|---|
| Voir le salon, Voir les anciens messages | ✅ | lire les sorties |
| Utiliser les commandes de l'application | ✅ | `/event creer`, etc. |
| Envoyer des messages | ❌ | pas de discussion dans le salon |
| Ajouter des réactions | ❌ | voir ci-dessous |
| Créer des fils publics / privés, Envoyer des messages dans les fils | ❌ | pas de fils de discussion |

Le réglage « Ajouter des réactions ❌ » fait le gros du travail. Sans cette permission, un membre peut toujours **cliquer sur une réaction déjà présente**, mais il ne peut pas en ajouter une nouvelle. Les joueurs n'ont donc accès qu'aux 3 émotes posées par le bot, et aucune autre émote ne peut apparaître. Envoyer des messages n'est pas nécessaire pour les commandes slash : c'est le bot qui poste.

**Le rôle du bot** (ajoute-le dans les permissions du salon) : ✅ Voir le salon, Envoyer des messages, Intégrer des liens, Ajouter des réactions, Gérer les messages, Voir les anciens messages. Sinon l'interdiction posée sur @everyone s'applique aussi à lui.

En complément, indique l'ID du salon dans `.env` (clic droit sur le salon → *Copier l'identifiant*, après avoir activé le mode développeur dans Paramètres → Avancés) :

```
EVENT_CHANNEL_IDS=123456789012345678
```

Le bot n'acceptera `/event creer` que dans ce salon. Il supprimera aussi tout message qu'un joueur arriverait quand même à y poster, par exemple à cause d'une permission mal réglée sur un rôle. Les messages des modérateurs (permission « Gérer les messages ») restent en place.

## Déploiement

### Avec Docker (recommandé)

```bash
mkdir -p data && sudo chown 1000:1000 data   # le conteneur tourne avec l'utilisateur 1000
docker compose up -d --build
docker compose logs -f
```

`restart: unless-stopped` relance le bot après un crash ou un redémarrage du serveur. La base SQLite et le cache des instances sont dans `./data` : sauvegarde ce dossier.

### Sans Docker (systemd, Linux)

```bash
sudo useradd --system --home /opt/wowplanner wowplanner
sudo git clone <ton-repo> /opt/wowplanner && cd /opt/wowplanner
sudo python3 -m venv .venv && sudo .venv/bin/pip install -r requirements.txt
sudo cp .env.example .env && sudo nano .env
sudo chown -R wowplanner: /opt/wowplanner
sudo cp deploy/wowplanner.service /etc/systemd/system/
sudo systemctl enable --now wowplanner
journalctl -u wowplanner -f
```

### En local (développement)

Il faut Python 3.11 ou plus récent.

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (Linux/macOS : source .venv/bin/activate)
pip install -r requirements.txt pytest
python -m pytest
python -m wowplanner
```

## Source des donjons et raids

Blizzard ne publie pas d'API pour WoW Forever. Le bot lit donc le tableau « Dungeons and raids » de la page [World of Warcraft: Forever](https://warcraft.wiki.gg/wiki/World_of_Warcraft:_Forever) du wiki communautaire, via son API MediaWiki :

- au démarrage, puis toutes les `INSTANCES_REFRESH_HOURS` heures (24 par défaut) ;
- à la demande avec `/instances maj`.

Le résultat est mis en cache dans `data/instances_cache.json`. Une liste intégrée (`wowplanner/instances_default.json`, à jour au 11/11/2026) sert de secours si le wiki est injoignable. Si la page change de structure et que le bot ne trouve plus qu'une liste suspecte (moins de 10 donjons ou aucun raid), la mise à jour est ignorée et l'ancienne liste est conservée.

## Structure

```
wowplanner/
  __main__.py         point d'entrée (python -m wowplanner)
  bot.py              client Discord, synchronisation des commandes
  config.py           lecture du .env
  db.py               SQLite : sorties + inscriptions
  embeds.py           rendu du message de sortie
  instances.py        liste des instances, lecture du wiki
  roles.py            rôles, compositions par défaut, correspondance des émotes
  timeparse.py        lecture des dates et heures
  cogs/events.py      /event + gestion des réactions
  cogs/instances.py   /instances + mise à jour périodique
tests/test_core.py
```
