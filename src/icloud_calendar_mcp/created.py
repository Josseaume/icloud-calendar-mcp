"""Mémoire des calendriers créés par Claude.

Claude a le droit d'écrire dans les calendriers qu'il a lui-même créés : ils
sont neufs, il n'y a rien d'ancien à y protéger. On les reconnaît à leur
adresse CalDAV (qui ne change pas si tu les renommes), notée dans :
    ~/.config/icloud-calendar-mcp/created_calendars.json

Ce fichier ne peut qu'AJOUTER des droits sur des calendriers créés par le
serveur : les calendriers protégés (Cours ESIEE) restent protégés quoi qu'il
contienne.
"""

import json
import os
import tempfile
from pathlib import Path

# Limite anti-emballement : si Claude se mettait à créer des calendriers en
# boucle (bug, texte piégé...), il serait arrêté au bout de 10.
MAX_CREATED = 10


class CreatedCalendars:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict[str, dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            return {}  # fichier illisible : on n'accorde aucun droit
        return data if isinstance(data, dict) else {}

    def contains(self, url: str) -> bool:
        return url in self.load()

    def usage(self, url: str) -> str | None:
        return self.load().get(url, {}).get("usage")

    def count(self) -> int:
        return len(self.load())

    def add(self, url: str, name: str, usage: str | None) -> None:
        data = self.load()
        data[url] = {"name": name, "usage": usage}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Écriture atomique : on écrit un fichier temporaire puis on le renomme,
        # pour ne jamais laisser un fichier à moitié écrit.
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".created-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)
