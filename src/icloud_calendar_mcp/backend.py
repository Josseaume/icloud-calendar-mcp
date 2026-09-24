"""Accès à iCloud en CalDAV. C'est le seul fichier qui parle au réseau.

Le reste du code ne manipule que des objets simples (CalendarRef...), ce qui
permet de tout tester avec un faux iCloud en mémoire (voir tests/).
"""

import logging
import re
import threading
from collections.abc import Callable, Iterator
from typing import TypeVar
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote, unquote, urlsplit

import caldav
import icalendar
from caldav.lib import error as caldav_error

# En mode DEBUG, ces bibliothèques peuvent journaliser des en-têtes HTTP,
# dont celui qui porte le mot de passe. On ne garde que les avertissements.
for _name in ("caldav", "niquests", "urllib3"):
    logging.getLogger(_name).setLevel(logging.WARNING)


T = TypeVar("T")


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
        # Claude peut appeler plusieurs outils en parallèle (chacun dans un thread) :
        # le verrou les fait passer un par un sur la connexion iCloud.
        self._lock = threading.RLock()

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
        """Un seul accès iCloud à la fois, et des erreurs traduites en messages sûrs."""
        try:
            with self._lock:
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
                # strip() : iCloud garde parfois un espace en fin de nom (« Soirée »).
                refs.append(CalendarRef(name=(cal.get_display_name() or url).strip(), url=url))
            return refs

    def _calendar(self, ref: CalendarRef) -> caldav.Calendar:
        if ref.url not in self._calendars:
            self.list_calendars()
        if ref.url not in self._calendars:
            raise BackendError(f"Calendrier « {ref.name} » introuvable sur iCloud.")
        return self._calendars[ref.url]

    # --- événements ------------------------------------------------------

    def search(self, ref: CalendarRef, start: datetime, end: datetime) -> list[tuple[str, icalendar.Component]]:
        """Événements d'un calendrier sur une période, récurrences dépliées.

        Renvoie des paires (event_id, VEVENT). Une réunion hebdomadaire donne une
        paire par occurrence, toutes avec le même event_id (celui de la série).
        """
        with self._errors():
            found = self._calendar(ref).search(start=start, end=end, event=True, expand=True)
            pairs = []
            for obj in found:
                event_id = event_id_from_url(str(obj.url))
                for comp in obj.get_icalendar_instance().walk("VEVENT"):
                    pairs.append((event_id, comp))
            return pairs

    def create(self, ref: CalendarRef, ical: str) -> str:
        """Enregistre un nouvel événement (texte .ics) ; renvoie son event_id."""
        with self._errors():
            event = self._calendar(ref).add_event(ical)
            return event_id_from_url(str(event.url))

    def update(self, ref: CalendarRef, event_id: str, mutate: Callable[[icalendar.Calendar], T]) -> T:
        """Relit l'événement, le passe à `mutate` pour modification, puis l'enregistre.

        L'enregistrement envoie l'« ETag » lu (sa version) : si l'événement a été
        modifié ailleurs entre-temps, iCloud refuse au lieu d'écraser.
        Les erreurs levées par `mutate` (refus de sécurité) remontent telles quelles.
        """
        url = event_url(ref, event_id)
        with self._errors():
            event = self._calendar(ref).event_by_url(url)
        with event.edit_icalendar_instance() as ical:
            result = mutate(ical)
        with self._errors():
            event.save()
        return result

    def get(self, ref: CalendarRef, event_id: str) -> tuple[icalendar.Calendar, str | None]:
        """Un événement et son ETag (l'empreinte de sa version actuelle)."""
        url = event_url(ref, event_id)
        with self._errors():
            event = self._calendar(ref).event_by_url(url)
            return event.get_icalendar_instance(), event.etag

    def delete(self, ref: CalendarRef, event_id: str, etag: str | None) -> None:
        """Supprime l'événement SEULEMENT s'il est encore dans la version `etag`.

        « If-Match » : iCloud refuse (412) si l'événement a changé depuis qu'il
        a été montré à Arthur pour confirmation. On supprime ce qu'il a validé,
        pas autre chose.
        """
        url = event_url(ref, event_id)
        headers = {"If-Match": etag} if etag else {}
        with self._errors():
            self._get_principal()
            response = self._client.request(url, "DELETE", "", headers)
            if response.status == 412:
                raise BackendError(
                    "L'événement a été modifié ailleurs depuis la confirmation : rien n'a été supprimé."
                )
            if response.status == 404:
                raise BackendError("L'événement n'existe plus (déjà supprimé ?).")
            if response.status not in (200, 204):
                raise BackendError(f"iCloud a refusé la suppression (HTTP {response.status}).")


# Caractères autorisés dans un event_id. Il vient de Claude, donc peut-être
# d'une injection : sans ce filtre, « ../autre-calendrier/x.ics » ferait
# sortir de l'adresse du calendrier autorisé (attaque « path traversal »).
_EVENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._@+=~-]{0,250}")


def validate_event_id(event_id: str) -> str:
    if not isinstance(event_id, str) or not _EVENT_ID.fullmatch(event_id):
        raise BackendError(f"event_id invalide : {event_id!r:.80}")
    return event_id


def event_url(ref: CalendarRef, event_id: str) -> str:
    """Adresse d'un événement, forcément À L'INTÉRIEUR du calendrier `ref`."""
    base = ref.url if ref.url.endswith("/") else ref.url + "/"
    return base + quote(validate_event_id(event_id), safe="._@+=~-")


def event_id_from_url(url: str) -> str:
    """« https://.../calendars/home/ABC-123.ics » -> « ABC-123.ics »."""
    return unquote(urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1])
