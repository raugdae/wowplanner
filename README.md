# WoW Planner

Bot Discord pour organiser des sorties donjon / raid sur **World of Warcraft: Forever**.

- `/ajouter event` publie un message de sortie : instance, date, nombre de joueurs et places par rôle.
- Les joueurs s'inscrivent avec les boutons sous le message : 🛡️ Tank, ⛑️ Heal, ⚔️ DPS, Se désinscrire.
- Chaque joueur déclare ses persos (`/ajouter perso`). À l'inscription, le bot prend le perso capable de tenir le rôle, ou demande lequel s'il y en a plusieurs.
- Quand un rôle est complet, son bouton passe en gris et les nouvelles inscriptions sont refusées.
- Chaque perso peut avoir un rôle préféré. Ses métiers et recettes sont lus dans l'armurerie Blizzard. Pour consulter les persos, métiers, recettes et donjons, il y a **le site web**. Côté Discord, `/liste battletags` donne les BattleTag de tout le monde.
- 30 minutes avant le départ, chaque inscrit reçoit un rappel en MP.
- 15 minutes avant le départ, le bot crée un salon vocal pour la sortie et ajoute son lien au message. Le salon est supprimé quand il est vide, au plus tôt 30 minutes après le début.
- La liste des donjons et raids vient de [warcraft.wiki.gg](https://warcraft.wiki.gg/wiki/World_of_Warcraft:_Forever) et se met à jour toute seule chaque nuit, avec le reste des données (voir « Synchro des données »).

## Commandes

Le bot ne garde que l'essentiel : les sorties, la déclaration des persos et l'atelier. Tout ce qui se consulte (persos, métiers, recettes, donjons, fiches d'armurerie) est sur **le site web**.

Les commandes suivent la logique **verbe + catégorie** :

| | event | perso | battletag | autre |
|---|---|---|---|---|
| **`/ajouter`** | crée une sortie | ✅ | ✅ | |
| **`/supprimer`** | annule la sortie | ✅ | ✅ | `inscrit` |
| **`/liste`** | `events` | | `battletags` | |

| Commande | Rôle |
|---|---|
| `/ajouter event instance date heure [joueurs] [tanks] [heals] [dps] [description]` | Crée une sortie. L'instance se cherche par nom ou abréviation (`brd`, `ony`, `sm cath`…). |
| `/ajouter perso nom [classe] [race] [role_prefere]` | Déclare un de tes persos. Seul le nom est obligatoire : classe et race sont lues dans l'armurerie si le perso y est (niveau 10+), sinon le bot les demande. La combinaison race/classe et le rôle préféré sont vérifiés. Pour corriger un perso : le supprimer et le recréer. |
| `/ajouter battletag tag` | Enregistre ton BattleTag (`Nom#1234`), ou remplace l'ancien. |
| `/supprimer event sortie` | Annule la sortie après confirmation, et prévient les inscrits. Réservé à l'organisateur et aux modérateurs. |
| `/supprimer inscrit sortie joueur` | Désinscrit un joueur d'**une** sortie. Choisis la sortie d'abord : le champ `joueur` ne propose que ses inscrits. Les autres sorties du joueur ne changent pas. Réservé à l'organisateur et aux modérateurs. |
| `/supprimer perso perso` | Supprime un perso et ses métiers. Ses inscriptions en cours restent, avec ton pseudo à la place. |
| `/supprimer battletag` | Retire ton BattleTag. |
| `/liste events` | Prochaines sorties du serveur. |
| `/liste battletags` | Les BattleTag des joueurs du serveur. |

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

- Les métiers ne se saisissent plus à la main : ils viennent de l'armurerie (niveau compris), à l'ajout du perso puis à chaque synchro. Sans clés Blizzard, les persos n'ont donc pas de métiers.
- `/liste battletags` ne montre que les joueurs vus sur le serveur : ceux qui y ont utilisé une commande du bot ou se sont inscrits à une sortie. La liste s'affiche seulement pour celui qui tape la commande.

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
| `/admin ajouter perso joueur nom [classe] [race] [role_prefere]` | Ajoute un perso à un membre, mêmes règles que `/ajouter perso`. Le membre reçoit un MP. |
| `/admin supprimer perso joueur perso` | Supprime un perso d'un membre (choisir le membre d'abord : le champ `perso` propose ses persos). Il reçoit un MP. |
| `/admin atelier` | Poste (et épingle) le panneau de l'atelier dans le salon courant. |
| `/admin sync` | Relit **tout** maintenant, sans attendre la synchro de nuit. Voir ci-dessous. |

### Synchro des données (nuit et `/admin sync`)

Tout ce qui vient de l'extérieur est mis à jour au même endroit (`cogs/sync.py`), en 5 étapes :
1. la liste des donjons et raids (wiki) ;
2. les priorités de stats (guide stillsixty) ;
3. les arbres de talents (Blizzard) ;
4. tous les persos déclarés : métiers, recettes, équipement, stats, talents, images (armurerie) ;
5. les détails des recettes : noms français, composants, objets fabriqués (Blizzard).

- **Chaque nuit à 4 h** (fuseau `TIMEZONE`), tout seul. Les talents ne sont redemandés que s'ils ont plus d'une semaine, et seules les recettes nouvelles sont demandées. Si le bot était éteint à 4 h (ou au premier lancement), la synchro est rattrapée au démarrage dès que la dernière a plus de 20 h. Le bilan est dans les logs.
- **`/admin sync`** : la même chose tout de suite, mais en forçant les talents et **toutes** les recettes. L'avancement s'affiche étape par étape. Si ça dépasse 15 minutes, Discord ne permet plus de mettre à jour la réponse : le bilan arrive en MP.

Une étape en échec n'empêche pas les suivantes, et on garde alors les anciennes données. Sans clés Blizzard, les étapes 3 à 5 sont sautées. Une seule synchro à la fois.

**Quotas Blizzard** : 100 requêtes par seconde et 36 000 par heure. Le bot fait au plus 5 requêtes en parallèle et marque une pause d'une seconde entre deux persos ; s'il reçoit malgré tout un refus pour excès de requêtes, il patiente puis réessaie. Ordre de grandeur pour un `/admin sync` : environ 550 requêtes pour les talents, 6 par perso, 2 par recette. Avec 50 persos et 1 000 recettes, ça fait environ 3 000 requêtes, moins de 10 % du quota horaire. La synchro de nuit en fait beaucoup moins (persos et recettes nouvelles seulement).

Pour voir les persos d'un membre : le site web.

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

- chaque nuit, avec la synchro de nuit ;
- à la demande avec `/admin sync`.

Le résultat est mis en cache dans `data/instances_cache.json`. Une liste intégrée (`wowplanner/instances_default.json`, à jour au 11/11/2026) sert de secours si le wiki est injoignable. Si la page change de structure et que le bot ne trouve plus qu'une liste suspecte (moins de 10 donjons ou aucun raid), la mise à jour est ignorée et l'ancienne liste est conservée.

## Armurerie WoW Forever

Facultatif : sans clés Blizzard, tout le reste du bot marche normalement.

**Activer** : crée un accès sur <https://develop.battle.net> (*Create Client*, gratuit) et renseigne
`BLIZZARD_CLIENT_ID`, `BLIZZARD_CLIENT_SECRET` et `BLIZZARD_REGION` dans `.env` (jamais dans `.env.example`, qui est
versionné).

**Ce que ça apporte**

- **Persos synchronisés** : quand un perso est trouvé, ses métiers (avec niveau), recettes connues, équipement,
  stats, talents et images sont repris de l'armurerie, pour le site. Synchro à `/ajouter perso`,
  chaque nuit pour tous les persos, et à la demande avec `/admin sync`.
- **Recettes** : les recettes connues sont relues à chaque synchro. Leurs détails (nom français, composants, objet
  fabriqué) sont demandés une seule fois puis gardés en base ; `/admin sync` les redemande tous.
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

Un petit site en lecture seule, pour parcourir les persos et les métiers du serveur. Il peut être réservé aux
membres du Discord (voir « Connexion avec Discord » plus bas) :

- **Persos** : tableau de tous les persos (classe, race, rôles, métiers et niveaux), recherche et filtres par classe,
  rôle ou métier ;
- **fiche d'un perso** : façon fiche du jeu, son **équipement** autour de son rendu en pied (icônes, infobulles,
  enchantements) et ses **caractéristiques** (chacune expliquée au survol ou au toucher : à quoi elle sert, avec une
  remarque selon la classe du perso, ex. « Force : inutile pour un Mage »), avec les **stats à pousser en priorité** pour sa spé (devinée d'après
  ses talents et son rôle préféré, avec un menu pour voir les autres spés de la classe). Les priorités viennent du
  guide WoW Forever de stillsixty.com, **relu chaque nuit à 4 h** avec la synchro de nuit :
  si le guide change, le site suit ; si la page ne répond pas ou change de forme, on garde les dernières connues. Puis ses métiers en tableau, et ses recettes par **onglet de métier**, classées par type d'objet
  (composants d'artisanat, potions, armure : torse…) ;
  le portrait apparaît aussi dans les listes. Images hébergées par Blizzard, mises à jour à chaque synchro ;
  ses **talents** comme dans le jeu (les trois arbres, icônes, rangs, infobulle au survol ou au toucher, double
  spé). Les arbres sont récupérés une fois par semaine auprès de Blizzard, les talents du perso à chaque synchro ;
- **Métiers** : qui a chaque métier et à quel niveau, et toutes les recettes connues sur le serveur, avec recherche
  (nom de recette, composant ou effet, ex. *agilité*) et liens vers les persos qui savent les faire. Chaque recette
  montre ce que fait l'objet, comme l'infobulle du jeu : emplacement, armure, dégâts, stats, effets « Utiliser » /
  « Équipé », niveau requis, nom coloré selon la qualité (et l'effet pour les enchantements) ;
- **Donjons** : les 35 donjons de WoW Forever (dont les 9 nouveaux) avec zone et tranche de niveau conseillée, les
  persos du serveur qui sont dans chaque tranche, et un choix de niveau (ou d'un perso) qui met en avant ce qui est à
  faire. Plus les raids (joueurs, boss, date d'ouverture). L'API Blizzard n'a pas le journal des donjons de Forever :
  la liste est dans `wowplanner/dungeons.py`, à retoucher si Blizzard change des tranches ;
- **fiche d'un donjon ou d'un raid** (clic dans la liste) : comment trouver l'entrée, ses coordonnées avec une
  commande `/way` à copier (TomTom), le **parcours des boss** numéroté (optionnels à part, avec où les trouver), les
  persos du serveur du bon niveau, la vignette Blizzard et un lien vers la carte détaillée du guide Warcraft Tavern.
  Les fiches sont dans `wowplanner/dungeon_guides.py` (noms français officiels des boss quand Blizzard les donne).

**Aucune info personnelle** : ni pseudo Discord, ni identifiant, ni BattleTag, et rien qui relie deux persos au même
joueur. Le site lit la même base que le bot (dans le même conteneur), donc il est toujours à jour. Il montre les persos
du serveur `GUILD_ID` (ou du seul serveur connu du bot).

### Connexion avec Discord

Avec `DISCORD_CLIENT_SECRET` renseigné, le site est **réservé aux membres du serveur Discord** :

| Pages | Sans connexion | Connecté (membre du serveur) |
|---|---|---|
| Persos, fiches persos, Métiers, recettes | page « Réservé aux membres » avec un bouton de connexion | ✅ |
| Donjons et fiches des donjons | ✅ sans les persos du serveur | ✅ avec les persos dans chaque tranche |

- **Connexion** : bouton « Se connecter avec Discord ». Discord demande d'autoriser le site à voir le pseudo, et rien d'autre (droit `identify` : ni serveurs, ni messages, ni e-mail). Le bot vérifie ensuite que la personne est membre du serveur. Pas besoin de l'intent « membres » : c'est une simple requête à l'API.
- **Durée** : la session dure 30 jours. L'appartenance au serveur est revérifiée une fois par jour : quelqu'un qui quitte le serveur ou qui en est exclu perd l'accès dans les 24 h.
- **Cookies** : signés, donc impossibles à falsifier, et lisibles seulement par le site (`HttpOnly`, `Secure` en HTTPS). La clé de signature est créée au premier lancement dans `data/session_secret`. La supprimer déconnecte tout le monde.
- Sans `DISCORD_CLIENT_SECRET`, le site reste ouvert à tous, et un avertissement le rappelle dans les logs au démarrage.

**Mise en place** (5 minutes) :
1. Ouvre le [portail développeur Discord](https://discord.com/developers/applications), puis l'application du bot, onglet **OAuth2**.
2. Dans **Redirects**, ajoute `https://wow.ton-domaine.fr/auth/callback` (ton adresse, suivie de `/auth/callback`). Enregistre.
3. Copie le **Client Secret** (bouton *Reset Secret* s'il n'est pas affiché) dans `.env` : `DISCORD_CLIENT_SECRET=…`. Ne le committe jamais.
4. Vérifie que `WEB_DOMAIN` (avec Traefik) ou `WEB_URL` est renseigné : c'est l'adresse de retour envoyée à Discord.
5. Lance `docker compose up -d`. Les logs doivent afficher « Site réservé aux membres du serveur ».

L'identifiant de l'application est repris automatiquement du bot (`DISCORD_CLIENT_ID` ne sert que pour en utiliser une autre). Si le secret est renseigné mais pas l'adresse du site, le site **ne démarre pas** plutôt que de rester ouvert par erreur.

**Avec Traefik** (réseau Docker externe partagé avec Traefik) : dans `.env`,

```
COMPOSE_FILE=docker-compose.yml:docker-compose.traefik.yml
WEB_DOMAIN=wow.ton-domaine.fr
# si besoin : TRAEFIK_NETWORK=…  TRAEFIK_ENTRYPOINT=…  TRAEFIK_CERTRESOLVER=…
```

puis `docker compose up -d --build`. `docker-compose.traefik.yml` ajoute les labels Traefik (HTTPS) et lance le site
sur le port interne 8080. Sans Docker : `WEB_PORT=8080` dans `.env`, et `WEB_URL=https://…` (adresse publique) pour
que le bot renvoie vers le site dans ses messages ; avec Traefik, `WEB_DOMAIN` suffit.

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
  cogs/commands.py    déclaration de toutes les commandes slash (/ajouter, /supprimer, /liste, /admin)
  cogs/events.py      sorties + boutons d'inscription
  cogs/characters.py  persos
  cogs/players.py     BattleTag
  cogs/armory.py      synchro armurerie : métiers, recettes, équipement, talents
  cogs/statsync.py    lecture des priorités de stats (guide stillsixty)
  cogs/sync.py        synchro de nuit et /admin sync : tout ce qui vient de l'extérieur
  cogs/orders.py      atelier : panneau, commandes entre persos, boutons en MP
  orders.py           règles des commandes (recettes commandables, droits, composants)
  recipes.py          recettes : recherche, regroupement, composants dépliés
  web.py              site web (persos, métiers, recettes, donjons)
  webauth.py          connexion au site avec Discord (OAuth2, cookies signés)
  cogs/schedule.py    rappels en MP et salons vocaux temporaires
tests/test_core.py
```
