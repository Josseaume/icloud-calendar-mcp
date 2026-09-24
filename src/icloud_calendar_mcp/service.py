"""Les règles de sécurité et la logique, sans aucun accès réseau direct.

Toute demande de Claude passe par ici avant d'atteindre iCloud : c'est ce
fichier qui décide ce qui est autorisé. Il parle à un « backend » (le vrai
iCloud, ou un faux en mémoire pendant les tests).
"""

from datetime import timedelta

from .backend import CalendarRef
from .config import Config, normalize
from .events import describe_period, from_component, range_bounds

# Une recherche couvre au plus ~3 mois : au-delà, Claude doit découper.
MAX_RANGE = timedelta(days=92)


class ServiceError(RuntimeError):
    """Refus ou erreur à expliquer à Claude (message sûr, en français)."""


class CalendarService:
    def __init__(self, backend, config: Config):
        self.backend = backend
        self.config = config

    # --- lecture ------------------------------------------------------------

    def list_calendars(self) -> list[dict]:
        result = []
        for cal in sorted(self.backend.list_calendars(), key=lambda c: normalize(c.name)):
            entry = {"name": cal.name, "writable": self._can_write(cal)}
            if self.config.is_protected(cal.name):
                entry["protected"] = True
            usage = self.config.usage(cal.name)
            if usage:
                entry["usage"] = usage
            result.append(entry)
        return result

    def list_events(self, start: str, end: str, calendar: str | None = None) -> dict:
        tz = self.config.timezone
        start_dt, end_dt = range_bounds(start, end, tz)
        if end_dt - start_dt > MAX_RANGE:
            raise ServiceError("Période trop longue (3 mois maximum) : découpe la recherche.")

        calendars = [self._find_calendar(calendar)] if calendar else self.backend.list_calendars()
        events = [
            from_component(comp, cal.name, event_id, tz)
            for cal in calendars
            for event_id, comp in self.backend.search(cal, start_dt, end_dt)
        ]
        events.sort(key=lambda e: e.sort_key())
        return {
            "period": describe_period(start_dt, end_dt),
            "count": len(events),
            "events": [e.to_dict() for e in events],
        }

    # --- outils internes ----------------------------------------------------

    def _find_calendar(self, name: str) -> CalendarRef:
        calendars = self.backend.list_calendars()
        matches = [c for c in calendars if normalize(c.name) == normalize(name)]
        if not matches:
            names = ", ".join(sorted(c.name for c in calendars))
            raise ServiceError(f"Calendrier « {name} » introuvable. Calendriers : {names}.")
        if len(matches) > 1:
            # Deux calendriers de même nom : impossible de savoir lequel est
            # autorisé, donc on refuse plutôt que de deviner.
            raise ServiceError(
                f"Plusieurs calendriers s'appellent « {name} » : renomme-en un dans l'app Calendrier."
            )
        return matches[0]

    def _can_write(self, cal: CalendarRef) -> bool:
        return self.config.can_write(cal.name)
