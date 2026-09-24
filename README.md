# icloud-calendar-mcp

Serveur MCP local qui permet à Claude (Claude Code, Claude Desktop, Cowork) de lire
et d'écrire dans l'agenda iCloud, via le protocole CalDAV. Les événements apparaissent
dans l'app Calendrier du Mac et de l'iPhone.

> « Bloque-moi lundi 18h-19h30 Basic Fit » → événement créé dans le calendrier Sport.

## Comment ça marche

```
Claude ──(MCP, stdin/stdout)──▶ serveur local ──(HTTPS, CalDAV)──▶ caldav.icloud.com
                                     │
                                     └── mot de passe lu dans le Trousseau macOS
```

- **Pas de service permanent** : Claude lance le serveur quand il en a besoin et
  l'arrête en se fermant. Aucun port réseau n'est ouvert.
- **CalDAV** : le protocole standard des agendas. Le même code marchera depuis le
  mini-PC Linux (seule la lecture du mot de passe sera à adapter).

| Fichier | Rôle |
|---|---|
| `server.py` | les outils que Claude voit, et la confirmation des suppressions |
| `service.py` | **les règles** : qui a le droit d'écrire où, ce qui est refusé |
| `backend.py` | le seul fichier qui parle à iCloud |
| `events.py` | lecture/écriture du format iCalendar, dates en français |
| `keychain.py` | lecture du mot de passe dans le Trousseau |
| `config.py`, `created.py` | configuration, mémoire des calendriers créés par Claude |
| `confirm.py` | fenêtre de confirmation macOS |

## Outils exposés à Claude

| Outil | Rôle |
|---|---|
| `list_calendars` | calendriers, droits, à quoi ils servent |
| `list_events` | événements d'une période (3 mois max), récurrences dépliées |
| `create_event` | crée un événement (horaire ou journée entière, lieu, notes, rappel) |
| `update_event` | modifie un événement (seuls les champs fournis) |
| `delete_event` | supprime un événement **après ta confirmation** |
| `create_calendar` | crée un calendrier (nom, couleur, usage) |
| `set_calendar_color` | change la couleur d'un calendrier modifiable |

## Sécurité : les choix et pourquoi

1. **Mot de passe dans le Trousseau, jamais dans un fichier.** Un `.env` peut partir
   sur GitHub (faute dans le `.gitignore`, `git add -f`), être lu par Claude en
   explorant le projet, ou être copié en clair dans les sauvegardes. La config refuse
   même de démarrer si une clé ressemble à un secret, et un hook Git refuse tout
   commit contenant quelque chose qui ressemble à un mot de passe pour app.
2. **Mot de passe pour app**, pas ton mot de passe Apple : révocable à tout moment
   sur appleid.apple.com. Attention, il ouvre aussi Mail et Contacts iCloud.
3. **Liste blanche** : Claude n'écrit que dans les calendriers listés dans
   `writable_calendars` (ou qu'il a créés). Tout le reste est en lecture seule.
4. **Calendriers protégés** (Cours ESIEE) : lecture seule quoi qu'il arrive, même
   s'ils sont ajoutés par erreur à la liste blanche.
5. **Suppression confirmée par toi, pas par Claude** : Claude ne voit que
   `calendar` et `event_id`. La question t'est posée par le client (Claude Code) ou,
   à défaut, par une fenêtre macOS (« Annuler » par défaut, 2 minutes). Sans
   réponse : rien n'est supprimé.
6. **On supprime ce que tu as validé** : la suppression est conditionnelle (ETag).
   Si l'événement a changé entre-temps sur l'iPhone, rien n'est supprimé.
7. **Données venues de tiers** : titres et notes (invitations, ADE) sont traités
   comme des données, jamais comme des instructions. Ils sont nettoyés, tronqués,
   et ne peuvent pas injecter de ligne dans un fichier iCalendar ni de code dans
   la fenêtre AppleScript (passés en argument).
8. **Pas de path traversal** : un `event_id` comme `../autre-calendrier/x.ics`
   est refusé, il ne peut pas faire sortir du calendrier autorisé.
9. **Aucun invité** : le serveur n'ajoute jamais de participant, donc n'envoie
   jamais rien à personne. Les événements avec invités ou récurrents ne sont ni
   modifiés ni supprimés (à faire dans l'app Calendrier).
10. **Pas de suppression ni de renommage de calendrier** par Claude, et au plus
    10 calendriers créés.

## Installation (sur un Mac)

```sh
brew install uv
git clone <dépôt> && cd icloud-calendar-mcp
git config core.hooksPath .githooks        # active le garde-fou anti-mot de passe
```

1. Crée un mot de passe pour app sur appleid.apple.com (Connexion et sécurité).
2. Enregistre-le dans le Trousseau, **dans ton propre Terminal** :
   ```sh
   security add-generic-password -s icloud-calendar-mcp -a TON_APPLE_ID -w
   ```
   `-w` en dernier = saisie au clavier, rien dans l'historique. Colle le mot de passe
   (format xxxx-xxxx-xxxx-xxxx) : rien ne s'affiche, c'est normal.
3. Copie `config.example.toml` vers `~/.config/icloud-calendar-mcp/config.toml`
   et adapte-le (Apple ID, calendriers modifiables, usages).
4. Vérifie : `uv run icloud-calendar-mcp check`

### Brancher dans Claude Code

```sh
claude mcp add --scope user icloud-calendar -- \
  /opt/homebrew/bin/uv run --directory "$PWD" icloud-calendar-mcp
```

### Brancher dans Claude Desktop (et Cowork)

Dans `~/Library/Application Support/Claude/claude_desktop_config.json` :

```json
{
  "mcpServers": {
    "icloud-calendar": {
      "command": "/opt/homebrew/bin/uv",
      "args": ["run", "--directory", "/chemin/vers/icloud-calendar-mcp", "icloud-calendar-mcp"]
    }
  }
}
```

Chemin complet vers `uv` obligatoire : Claude Desktop ne connaît pas le PATH du
terminal. Redémarre Claude Desktop ensuite.

## Tests

```sh
uv run pytest        # 99 tests, sans réseau (faux iCloud en mémoire)
```

## Désinstaller proprement

```sh
claude mcp remove icloud-calendar -s user
# Claude Desktop : retirer "icloud-calendar" de mcpServers, puis redémarrer
security delete-generic-password -s icloud-calendar-mcp
rm -rf ~/.config/icloud-calendar-mcp
uv cache clean && uv python uninstall --all
brew uninstall uv
```

Puis révoque le mot de passe pour app sur appleid.apple.com.

## Limites connues

- Événements récurrents et événements avec invités : lecture seule.
- Lecture du mot de passe : macOS uniquement pour l'instant (sur le mini-PC
  Linux, il faudra un autre coffre, par exemple Secret Service).
