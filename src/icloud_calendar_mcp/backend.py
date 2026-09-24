"""Accès à iCloud en CalDAV. C'est le seul fichier qui parle au réseau.

Le reste du code ne manipule que des objets simples (CalendarRef...), ce qui
permet de tout tester avec un faux iCloud en mémoire (voir tests/).
"""

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import caldav
from caldav.lib import error as caldav_error

# En mode DEBUG, ces bibliothèques peuvent journaliser des en-têtes HTTP,
# dont celui qui porte le mot de passe. On ne garde que les avertissements.
for _name in ("caldav", "niquests", "urllib3"):
    logging.getLogger(_name).setLevel(logging.WARNING)


class BackendError(RuntimeError):
    """Erreur iCloud, avec un message sûr (jamais de mot de passe dedans)."""


@dataclass(frozen=True)
class CalendarRef:
    """Un calendrier iCloud : son nom affiché et son adresse CalDAV."""

    name: str
    url: str


class CaldavBackend:
    def __init__(self, url: str, username: str, password_provider: Callable[[], str]):
        self._url = url
        self._username = username
        # On reçoit une fonction plutôt que le mot de passe : il n'est lu dans
        # le Trousseau qu'au premier vrai besoin.
        self._password_provider = password_provider
        self._password: str | None = None
        self._client: caldav.DAVClient | None = None
        self._principal = None
        self._calendars: dict[str, caldav.Calendar] = {}
        self._holds_events: dict[str, bool] = {}

    # --- connexion -------------------------------------------------------

    def _get_principal(self):
        if self._principal is None:
            self._password = self._password_provider()
            self._client = caldav.DAVClient(
                url=self._url,
                username=self._username,
                password=self._password,
                timeout=30,
            )
            # « principal » = ton compte vu par CalDAV ; c'est lui qui connaît
            # la liste de tes calendriers.
            self._principal = self._client.principal()
        return self._principal

    @contextmanager
    def _errors(self) -> Iterator[None]:
        """Traduit les erreurs réseau/CalDAV en messages clairs et sûrs."""
        try:
            yield
        except BackendError:
            raise
        except caldav_error.AuthorizationError:
            raise BackendError(
                "iCloud refuse la connexion : Apple ID ou mot de passe pour app "
                "incorrect, ou mot de passe révoqué."
            ) from None
        except caldav_error.NotFoundError:
            raise BackendError("Élément introuvable sur iCloud (supprimé entre-temps ?).") from None
        except caldav_error.ETagMismatchError:
            raise BackendError(
                "L'événement a été modifié ailleurs entre-temps (iPhone, Mac...). "
                "Relis-le puis recommence."
            ) from None
        except Exception as exc:  # réseau coupé, iCloud en panne, réponse inattendue...
            raise BackendError(self._scrub(f"Erreur iCloud ({type(exc).__name__}) : {exc}")[:300]) from None

    def _scrub(self, text: str) -> str:
        """Filet de sécurité : efface le mot de passe s'il apparaît dans un texte."""
        if self._password:
            text = text.replace(self._password, "***")
        return text

    # --- calendriers -----------------------------------------------------

    def list_calendars(self) -> list[CalendarRef]:
        """Calendriers qui acceptent des événements (on écarte les listes de rappels)."""
        with self._errors():
            refs = []
            for cal in self._get_principal().calendars():
                url = str(cal.url)
                if url not in self._holds_events:
                    self._holds_events[url] = "VEVENT" in cal.get_supported_components()
                if not self._holds_events[url]:
                    continue
                self._calendars[url] = cal
                refs.append(CalendarRef(name=cal.get_display_name() or url, url=url))
            return refs
