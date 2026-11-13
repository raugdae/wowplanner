# WoW Planner

Bot Discord pour organiser des sorties donjon / raid sur **World of Warcraft: Forever**.

- `/ajouter event` publie un message de sortie : instance, date, nombre de joueurs et places par rôle.
- Les joueurs s'inscrivent avec les boutons sous le message : 🛡️ Tank, ⛑️ Heal, ⚔️ DPS, Se désinscrire.
- Chaque joueur déclare ses persos (`/ajouter perso`). À l'inscription, le bot prend le perso capable de tenir le rôle, ou demande lequel s'il y en a plusieurs.
- Quand un rôle est complet, son bouton passe en gris et les nouvelles inscriptions sont refusées.
- Chaque perso peut avoir un rôle préféré et ses métiers. `/liste metier` retrouve qui a un métier donné, et `/liste battletags` donne les BattleTag de tout le monde.
- 30 minutes avant le départ, chaque inscrit reçoit un rappel en MP.
- 15 minutes avant le départ, le bot crée un salon vocal pour la sortie et ajoute son lien au message. Le salon est supprimé quand il est vide, au plus tôt 30 minutes après le début.
- La liste des donjons et raids vient de [warcraft.wiki.gg](https://warcraft.wiki.gg/wiki/World_of_Warcraft:_Forever) et se met à jour toute seule une fois par jour.

## Commandes

Toutes les commandes suivent la logique **verbe + catégorie** : `/ajouter`, `/modifier`, `/supprimer`, `/liste`, puis ce sur quoi ça porte.

| | event | perso | metier | battletag | autre |
|---|---|---|---|---|---|
| **`/ajouter`** | crée une sortie | ✅ | ✅ | ✅ | |
| **`/modifier`** | | nom, classe, race, rôle préféré | niveau | | `armurerie` · `instances` (modos) |
| **`/supprimer`** | annule la sortie | ✅ | ✅ | ✅ | `inscrit` |
| **`/liste`** | `events` | `persos` | `metier` (qui l'a) · `recettes` | `battletags` | `instances` · `armurerie` |

| Commande | Rôle |
|---|---|
| `/ajouter event instance date heure [joueurs] [tanks] [heals] [dps] [description]` | Crée une sortie. L'instance se cherche par nom ou abréviation (`brd`, `ony`, `sm cath`…). |
| `/ajouter perso nom [classe] [race] [role_prefere]` | Déclare un de tes persos. Seul le nom est obligatoire : classe et race sont lues dans l'armurerie si le perso y est (niveau 10+), sinon le bot les demande. La combinaison race/classe et le rôle préféré sont vérifiés. |
| `/ajouter metier perso metier [niveau]` | Ajoute un métier à un perso (niveau 1 à 300). 2 métiers principaux maximum. |
| `/ajouter battletag tag` | Enregistre ton BattleTag (`Nom#1234`), ou remplace l'ancien. |
| `/modifier perso perso [nom] [classe] [race] [role_prefere]` | Modifie un perso sans perdre ses métiers ni ses inscriptions. Rôle préféré « Aucun » pour le retirer. |
| `/modifier metier perso metier niveau` | Change le niveau d'un métier. |
| `/modifier armurerie [perso]` | Relit tout de suite tes persos (ou l'un d'eux) dans l'armurerie : métiers, recettes. Une fois par minute maximum. |
| `/modifier instances` | Recharge la liste des donjons/raids depuis le wiki (permission « Gérer le serveur »). |
| `/supprimer event sortie` | Annule la sortie après confirmation, et prévient les inscrits. Réservé à l'organisateur et aux modérateurs. |
| `/supprimer inscrit sortie joueur` | Désinscrit un joueur d'**une** sortie. Choisis la sortie d'abord : le champ `joueur` ne propose que ses inscrits. Les autres sorties du joueur ne changent pas. Réservé à l'organisateur et aux modérateurs. |
| `/supprimer perso perso` | Supprime un perso et ses métiers. Ses inscriptions en cours restent, avec ton pseudo à la place. |
| `/supprimer metier perso metier` | Retire un métier. |
| `/supprimer battletag` | Retire ton BattleTag. |
| `/liste events` | Prochaines sorties du serveur. |
| `/liste persos [joueur]` | Tes persos (ou ceux d'un autre joueur) : rôles possibles, rôle préféré ⭐, métiers, BattleTag. |
| `/liste metier metier` | Les persos du serveur qui ont ce métier, du plus haut niveau au plus bas. |
| `/liste battletags` | Les BattleTag des joueurs du serveur. |
| `/liste instances [type]` | Les donjons (avec niveaux) et les raids. |
| `/liste recettes metier [recherche]` | Recettes du métier connues sur le serveur, avec composants et persos qui savent les faire, envoyées en MP (pages ◀ ▶). Si rien ne correspond, réponse privée dans le salon. |
| `/liste armurerie perso` | Fiche armurerie d'un perso (stats, équipement, métiers), envoyée en MP. Voir « Armurerie WoW Forever ». |

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

- Le message affiche les inscrits sous chaque rôle, dans l'ordre d'inscription : perso, classe et pseudo Discord. Sur les gros raids, le pseudo est retiré si la liste devient trop longue pour Discord.
- Un seul rôle par joueur. Cliquer sur un autre rôle te déplace, s'il reste de la place. Recliquer sur ton rôle permet de changer de perso sans perdre ta place.
- **Choix du perso** :
  - un seul de tes persos peut tenir le rôle : il est pris automatiquement ;
  - plusieurs : un menu visible seulement par toi demande lequel. Les persos dont c'est le rôle préféré ⭐ sont en tête, rien n'est présélectionné ;
  - aucun perso déclaré : tu es inscrit avec ton pseudo Discord ;
  - des persos, mais aucun pour ce rôle : inscription refusée, le bot liste ce que tes persos peuvent jouer.
- Les réponses du bot visibles seulement par toi ne s'empilent pas : à ta commande ou ton clic suivant, la précédente est effacée. Discord ne le permet que pendant 15 minutes ; au-delà, elle reste jusqu'à ce que tu la fermes ou recharges Discord.
- Si le bot redémarre, les boutons continuent de marcher. Les sorties créées avec l'ancienne version (inscription par réaction) sont converties au démarrage : les réactions sont retirées, les inscrits sont gardés.

### Classes et rôles

| Classe | Tank | Heal | DPS |
|---|:-:|:-:|:-:|
| Guerrier | ✅ | | ✅ |
| Paladin | ✅ | ✅ | ✅ |
| Druide | ✅ | ✅ | ✅ |
| Prêtre | | ✅ | ✅ |
| Chaman | | ✅ | ✅ |
| Chasseur, Voleur, Mage, Démoniste | | | ✅ |

Le Paladin tank est viable dans Forever (Seal of Fury, Consecration de base). Le Chaman n'est pas compté comme tank : l'Amélioration peut dépanner en petit groupe, mais ce n'est pas un rôle prévu. Les combinaisons race/classe suivent le [wiki](https://warcraft.wiki.gg/wiki/World_of_Warcraft:_Forever), Éolides (Skyborne) compris, sans distinction de faction. Tout est dans `wowplanner/gamedata.py`.

### Métiers et BattleTag

- Métiers principaux : Alchimie, Forge, Enchantement, Ingénierie, Herboristerie, Travail du cuir, Minage, Dépeçage, Couture (2 maximum par perso). Secondaires : Cuisine, Secourisme, Pêche. C'est la même liste qu'en Classic : le « Camping » de Forever est un système de feux de camp, pas un métier.
- Le niveau de métier est facultatif. Pense à le mettre à jour avec `/modifier metier`.
- Les listes (`/liste metier`, `/liste battletags`) ne montrent que les joueurs vus sur le serveur : ceux qui y ont utilisé une commande du bot ou se sont inscrits à une sortie. Elles s'affichent seulement pour celui qui tape la commande.

### Rappel et salon vocal

- **Rappel** (`REMINDER_MINUTES`, 30 par défaut) : un MP à chaque inscrit, avec son rôle et le lien de la sortie. Pas de rappel si la sortie a été créée moins de 30 minutes avant le départ. Les joueurs qui ont fermé leurs MP ne le reçoivent pas.
- **Salon vocal** (`VOICE_CHANNEL_MINUTES`, 15 par défaut) : créé seulement s'il y a au moins un inscrit, dans la catégorie du salon des sorties (ou `VOICE_CATEGORY_ID`), limité au nombre de joueurs de la sortie. Il est ouvert à tous ceux qui peuvent voir la catégorie. Il est supprimé dès qu'il est vide, au plus tôt 30 minutes après le début, ou dès que la sortie est annulée (s'il est vide).
- Si le bot était éteint au moment prévu, le salon vocal est quand même créé à son retour, tant que la sortie a commencé depuis moins d'une heure. Rien n'est envoyé ni créé en double.
- Mettre `0` désactive la fonction correspondante.

### Commandes d'administration (`/admin`)

Pour gérer les persos des membres (qui ont la flemme 😄). **Réservé à la permission « Gérer le serveur »** : les
autres membres ne voient même pas `/admin`. Pour l'ouvrir à un rôle (ex. « Officier ») : *Paramètres du serveur →
Intégrations → WoW Planner → `/admin`*. Le bot revérifie la permission à chaque utilisation.

| Commande | Rôle |
|---|---|
| `/admin ajouter perso joueur nom [classe] [race] [role_prefere]` | Ajoute un perso à un membre, mêmes règles que `/ajouter perso`. Le membre reçoit un MP et peut ensuite le modifier lui-même. |
| `/admin modifier perso joueur perso [nom] [classe] [race] [role_prefere]` | Modifie un perso d'un membre (choisir le membre d'abord : le champ `perso` propose ses persos). |
| `/admin supprimer perso joueur perso` | Supprime un perso d'un membre (il reçoit un MP). |
| `/admin modifier armurerie [joueur]` | Relit dans l'armurerie les persos d'un membre, ou de tout le serveur. Sans limite de fréquence. |
| `/admin atelier` | Poste (et épingle) le panneau de l'atelier dans le salon courant. |

Pour voir les persos d'un membre, `/liste persos joueur:@membre` suffit (ouvert à tous).

## Atelier : commandes entre persos

Pour demander à un autre joueur de fabriquer un objet, sans commande à taper. Un admin poste le panneau
une fois avec `/admin atelier` ; il reste épinglé avec deux boutons :

- **🛒 Commander** : une petite fenêtre demande l'objet (un bout du nom suffit : *mangouste*), la quantité et un
  mot pour l'artisan. Le bot trouve la recette et qui sait la faire (menu si plusieurs choix), montre un récap
  avec les composants nécessaires (sous-recettes dépliées, quantités recalculées), puis envoie la commande en MP
  à l'artisan.
- **📦 Mes commandes** : commandes passées et reçues, en cours et récentes ; un menu permet d'accepter, terminer
  ou annuler.

Côté artisan, le MP a les boutons **Accepter** / **Refuser**, puis **C'est prêt** / **Abandonner**. Le client
reçoit un MP à chaque étape et peut **annuler** tant que ce n'est pas prêt. Composants et livraison se règlent
entre eux en jeu (courrier, échange).

Seules les recettes **débloquées par les persos du serveur** (vues dans l'armurerie) sont proposées, et jamais
à ses propres persos. Pas de sécurité à ajouter : Discord dit qui clique ; seul le propriétaire du perso artisan
peut accepter ou terminer, seul le client peut annuler. Les boutons marchent encore après un redémarrage du bot.

Raccourci pour les habitués : `/commander objet:… [quantite] [note]`, avec autocomplétion.

## Installation

### 1. Créer le bot sur Discord

1. Ouvre <https://discord.com/developers/applications> et clique sur **New Application**.
2. Dans l'onglet **Bot**, clique sur **Reset Token** et copie le token. Aucun *Privileged Gateway Intent* n'est nécessaire.
3. Dans l'onglet **OAuth2 → URL Generator**, coche les scopes `bot` et `applications.commands`, puis ces permissions :
   View Channel, **Manage Channels** (pour les salons vocaux des sorties), Send Messages, Embed Links, **Manage Messages** (pour garder le salon des sorties propre), Read Message History.
   Tu peux aussi utiliser directement le lien suivant, en remplaçant `CLIENT_ID` :
   `https://discord.com/oauth2/authorize?client_id=CLIENT_ID&scope=bot+applications.commands&permissions=93200`
4. Ouvre le lien et invite le bot sur ton serveur.

### 2. Configurer

```bash
cp .env.example .env
# puis renseigne DISCORD_TOKEN, et GUILD_ID pour que les commandes apparaissent tout de suite
```

Pour utiliser des émotes du serveur à la place des émotes par défaut : `EMOJI_TANK=<:tank:123456789012345678>`. Pour trouver l'ID d'une émote, tape `\:tank:` dans Discord.

### 3. Configurer le salon des sorties

L'objectif est que, dans ce salon, les joueurs ne puissent que lancer les commandes et cliquer sur les boutons. Ça se règle dans Discord : **Modifier le salon → Permissions**.

**@everyone** :

| Permission | Réglage | Pourquoi |
|---|---|---|
| Voir le salon, Voir les anciens messages | ✅ | lire les sorties |
| Utiliser les commandes de l'application | ✅ | `/ajouter event`, etc. |
| Envoyer des messages | ❌ | pas de discussion dans le salon |
| Ajouter des réactions | ❌ | pas d'émotes sur les sorties |
| Créer des fils publics / privés, Envoyer des messages dans les fils | ❌ | pas de fils de discussion |

Les boutons marchent sans aucune permission particulière, et envoyer des messages n'est pas nécessaire pour les commandes slash : c'est le bot qui poste.

**Le rôle du bot** (ajoute-le dans les permissions du salon) : ✅ Voir le salon, Envoyer des messages, Intégrer des liens, Gérer les messages, Voir les anciens messages. Sinon l'interdiction posée sur @everyone s'applique aussi à lui.

En complément, indique l'ID du salon dans `.env` (clic droit sur le salon → *Copier l'identifiant*, après avoir activé le mode développeur dans Paramètres → Avancés) :

```
EVENT_CHANNEL_IDS=123456789012345678
```

Le bot n'acceptera `/ajouter event` que dans ce salon. Il supprimera aussi tout message qu'un joueur arriverait quand même à y poster, par exemple à cause d'une permission mal réglée sur un rôle. Les messages des modérateurs (permission « Gérer les messages ») restent en place.

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
- à la demande avec `/modifier instances`.

Le résultat est mis en cache dans `data/instances_cache.json`. Une liste intégrée (`wowplanner/instances_default.json`, à jour au 11/11/2026) sert de secours si le wiki est injoignable. Si la page change de structure et que le bot ne trouve plus qu'une liste suspecte (moins de 10 donjons ou aucun raid), la mise à jour est ignorée et l'ancienne liste est conservée.

## Armurerie WoW Forever

Facultatif : sans clés Blizzard, tout le reste du bot marche normalement.

**Activer** : crée un accès sur <https://develop.battle.net> (*Create Client*, gratuit) et renseigne
`BLIZZARD_CLIENT_ID`, `BLIZZARD_CLIENT_SECRET` et `BLIZZARD_REGION` dans `.env` (jamais dans `.env.example`, qui est
versionné).

**Ce que ça apporte**

- `/liste armurerie perso` : fiche d'un perso (déclaré ou pas) **envoyée en MP**, pour la garder sans encombrer le
  salon : avatar, niveau, guilde, spé active, item level, stats, métiers avec niveau, équipement. Si les MP du joueur
  sont fermés, la fiche s'affiche en réponse privée.
- **Métiers synchronisés** : quand un perso est trouvé, ses métiers et leurs niveaux sont repris de l'armurerie (ils
  remplacent la saisie manuelle). Synchro à `/ajouter perso`, quand le nom change avec `/modifier perso`, à chaque
  `/liste armurerie`, et une fois par jour pour tous les persos.
- `/liste recettes metier [recherche]` : toutes les recettes du métier connues par les persos du serveur, avec
  leurs composants (en français) et les persos qui savent les faire, **en MP**. Une carte par recette (nom complet,
  un composant par ligne, 👥 les persos), regroupées par famille (Élixirs, Potions…), 3 par ligne sur PC ; environ
  45 recettes par page, pages ◀ ▶ au-delà. Un composant lui-même fabriqué par une recette connue sur le serveur est
  déplié en dessous, quantités recalculées (ex. : 3× Rouleau d'étoffe de lin ↳ 6× Étoffe de lin). `recherche` filtre sur le nom, sans tenir compte des accents ni des majuscules. Si aucune
  recette ne correspond, le bot répond seulement dans le salon, sans MP. Les recettes connues sont relues à chaque
  synchro ; les composants d'une recette sont demandés une seule fois puis gardés en base.
- **Vérification à l'ajout** : `/ajouter perso` dit si le perso existe dans l'armurerie, et prévient si la classe ou
  la race déclarée ne correspond pas. Jamais bloquant.

**Limites** (l'API n'est pas documentée officiellement pour Forever) : un perso n'apparaît qu'à partir du **niveau
10**, après une déconnexion, parfois avec plusieurs heures de retard. Les persos s'y adressent sans serveur, par
`prénom-nom` (`/profile/wow/character/grommash-hurlenfer?namespace=profile-forever-eu`). Si l'armurerie ne répond
pas, le bot le signale et continue.

**Tester l'accès** sans lancer le bot :

```bash
# Sur le VPS, avec Docker
docker compose run --rm wowplanner python -m wowplanner.armory_probe "Grommash Hurlenfer"
# En local
python -m wowplanner.armory_probe "Grommash Hurlenfer"
```

Le script vérifie le jeton et quelques données de jeu, interroge la fiche, les stats, l'équipement, les métiers, la
spé et l'image, puis enregistre chaque réponse brute dans `data/armory_probe/*.json`.

## Site web (facultatif)

Un petit site public, en lecture seule, pour parcourir les persos et les métiers du serveur :

- **Persos** : tableau de tous les persos (classe, race, rôles, métiers et niveaux), recherche et filtres par classe,
  rôle ou métier ;
- **fiche d'un perso** : ses métiers et ses recettes (composants dépliés) ;
- **Métiers** : qui a chaque métier et à quel niveau, et toutes les recettes connues sur le serveur, avec recherche
  (nom de recette ou composant) et liens vers les persos qui savent les faire.

**Aucune info personnelle** : ni pseudo Discord, ni identifiant, ni BattleTag, et rien qui relie deux persos au même
joueur. Le site lit la même base que le bot (dans le même conteneur), donc il est toujours à jour. Il montre les persos
du serveur `GUILD_ID` (ou du seul serveur connu du bot).

**Avec Traefik** (réseau Docker externe partagé avec Traefik) : dans `.env`,

```
COMPOSE_FILE=docker-compose.yml:docker-compose.traefik.yml
WEB_DOMAIN=wow.ton-domaine.fr
# si besoin : TRAEFIK_NETWORK=…  TRAEFIK_ENTRYPOINT=…  TRAEFIK_CERTRESOLVER=…
```

puis `docker compose up -d --build`. `docker-compose.traefik.yml` ajoute les labels Traefik (HTTPS) et lance le site
sur le port interne 8080. Sans Docker : `WEB_PORT=8080` dans `.env`.

## Structure

```
wowplanner/
  __main__.py         point d'entrée (python -m wowplanner)
  bot.py              client Discord, synchronisation des commandes
  config.py           lecture du .env
  db.py               SQLite : sorties, inscriptions, persos
  embeds.py           rendu du message de sortie
  instances.py        liste des instances, lecture du wiki
  roles.py            rôles, compositions par défaut, émotes
  gamedata.py         classes, races, rôles et métiers de WoW Forever
  armory.py           client de l'API Blizzard (armurerie Forever)
  armory_probe.py     script de test de l'armurerie
  timeparse.py        lecture des dates et heures
  cogs/commands.py    déclaration de toutes les commandes slash (/ajouter, /modifier, /supprimer, /liste)
  cogs/events.py      sorties + boutons d'inscription
  cogs/characters.py  persos et métiers
  cogs/players.py     BattleTag
  cogs/instances.py   instances + mise à jour périodique
  cogs/armory.py      /liste armurerie et /liste recettes, synchro des métiers et recettes
  cogs/orders.py      atelier : panneau, commandes entre persos, boutons en MP
  orders.py           règles des commandes (recettes commandables, droits, composants)
  recipes.py          mise en forme des recettes (recherche, pages)
  web.py              site web public (persos, métiers, recettes)
  cogs/schedule.py    rappels en MP et salons vocaux temporaires
tests/test_core.py
```
