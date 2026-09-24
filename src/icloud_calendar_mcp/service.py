"""Les règles de sécurité et la logique, sans aucun accès réseau direct.

Toute demande de Claude passe par ici avant d'atteindre iCloud : c'est ce
fichier qui décide ce qui est autorisé. Il parle à un « backend » (le vrai
iCloud, ou un faux en mémoire pendant les tests).
"""

import uuid
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone

import icalendar

from .backend import CalendarRef, validate_event_id
from .config import Config, normalize
from .events import (
    LOCATION_MAX,
    NOTES_MAX,
    TITLE_MAX,
    EventInfo,
    EventInputError,
    build_ical,
    check_duration,
    clean_text,
    describe_period,
    event_times,
    from_component,
    parse_when,
    range_bounds,
    replace_prop,
)

# Une recherche couvre au plus ~3 mois : au-delà, Claude doit découper.
MAX_RANGE = timedelta(days=92)


class ServiceError(RuntimeError):
    """Refus ou erreur à expliquer à Claude (message sûr, en français)."""


class CalendarService:
    def __init__(self, backend, config: Config, clock: Callable[[], datetime] | None = None):
        self.backend = backend
        self.config = config
        self.clock = clock or (lambda: datetime.now(timezone.utc))

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

    # --- écriture -------------------------------------------------------------

    def create_event(self, calendar: str | None, title: str, start: str, end: str | None = None,
                     all_day: bool = False, location: str | None = None, notes: str | None = None,
                     alert_minutes_before: int | None = None) -> dict:
        # 1. Le droit d'écrire est vérifié AVANT tout le reste.
        target = self._writable_calendar(calendar)
        # 2. Puis les données, nettoyées et validées.
        tz = self.config.timezone
        title = clean_text(title, "Le titre", TITLE_MAX)
        if not title:
            raise EventInputError("Le titre est obligatoire.")
        location = clean_text(location, "Le lieu", LOCATION_MAX)
        notes = clean_text(notes, "Les notes", NOTES_MAX, multiline=True)
        start_value, end_value = event_times(start, end, all_day, tz)

        # 3. Les chevauchements, cherchés AVANT de créer (sinon on se trouverait soi-même).
        conflicts = [] if all_day else self._conflicts(start_value, end_value)

        now = self.clock()
        ical = build_ical(uid=str(uuid.uuid4()).upper(), title=title, start=start_value, end=end_value,
                          all_day=all_day, location=location, notes=notes,
                          alert_minutes=alert_minutes_before, now=now)
        event_id = self.backend.create(target, ical)

        created = EventInfo(calendar=target.name, event_id=event_id, title=title, start=start_value,
                            end=end_value, all_day=all_day, location=location, notes=notes)
        result = {"created": created.to_dict()}
        if conflicts:
            result["conflicts"] = conflicts
        if self._is_past(start_value, now):
            result["warning"] = "Attention : cet événement est dans le passé."
        return result

    def update_event(self, calendar: str | None, event_id: str, title: str | None = None,
                     start: str | None = None, end: str | None = None,
                     location: str | None = None, notes: str | None = None) -> dict:
        target = self._writable_calendar(calendar)
        validate_event_id(event_id)
        if all(v is None for v in (title, start, end, location, notes)):
            raise EventInputError("Rien à modifier : donne au moins un champ.")
        tz = self.config.timezone
        title = clean_text(title, "Le titre", TITLE_MAX)
        if title == "":
            raise EventInputError("Le titre ne peut pas être vide.")
        location = clean_text(location, "Le lieu", LOCATION_MAX)
        notes = clean_text(notes, "Les notes", NOTES_MAX, multiline=True)
        new_start = parse_when(start, tz) if start else None
        new_end = parse_when(end, tz) if end else None
        now = self.clock()

        def mutate(ical: icalendar.Calendar) -> EventInfo:
            # Ces vérifications portent sur la version FRAÎCHEMENT relue, celle
            # qui sera enregistrée : pas de décalage possible entre contrôle et écriture.
            vevent = self._editable_vevent(ical)
            if title is not None:
                replace_prop(vevent, "SUMMARY", title)
            if location is not None:
                replace_prop(vevent, "LOCATION", location)  # "" = supprimer le lieu
            if notes is not None:
                replace_prop(vevent, "DESCRIPTION", notes)  # "" = supprimer les notes
            if new_start is not None or new_end is not None:
                self._move(vevent, new_start, new_end)
            replace_prop(vevent, "DTSTAMP", now)
            replace_prop(vevent, "LAST-MODIFIED", now)
            ical.add_missing_timezones()
            return from_component(vevent, target.name, event_id, tz)

        updated = self.backend.update(target, event_id, mutate)
        return {"updated": updated.to_dict()}

    def _move(self, vevent: icalendar.Component, new_start, new_end) -> None:
        """Change les horaires. Si seul le début change, la durée est conservée."""
        old_start = vevent.decoded("DTSTART")
        all_day = not isinstance(old_start, datetime)
        if "DTEND" in vevent:
            old_end = vevent.decoded("DTEND")
        elif "DURATION" in vevent:
            old_end = old_start + vevent.decoded("DURATION")
        else:
            old_end = old_start + (timedelta(days=1) if all_day else timedelta(0))

        for value in (new_start, new_end):
            if value is not None and isinstance(value, datetime) == all_day:
                raise EventInputError(
                    "Pour passer d'une journée entière à un horaire (ou l'inverse), "
                    "supprime l'événement et recrée-le."
                )
        start = new_start if new_start is not None else old_start
        if new_end is not None:
            end = new_end + timedelta(days=1) if all_day else new_end  # fin de journée entière : lendemain
        else:
            end = start + (old_end - old_start)
        if all_day:
            if end <= start:
                raise EventInputError("Le dernier jour doit être le même jour ou après le premier.")
        else:
            check_duration(start, end)
        vevent.pop("DURATION", None)
        replace_prop(vevent, "DTSTART", start)
        replace_prop(vevent, "DTEND", end)

    def _conflicts(self, start: datetime, end: datetime) -> list[dict]:
        """Événements à horaire qui chevauchent le créneau, dans tous les calendriers."""
        found = []
        for cal in self.backend.list_calendars():
            for event_id, comp in self.backend.search(cal, start, end):
                info = from_component(comp, cal.name, event_id, self.config.timezone)
                if not info.all_day:
                    found.append({"calendar": info.calendar, "title": info.title,
                                  "when": info.to_dict()["when"]})
        return found

    @staticmethod
    def _is_past(start: datetime | date, now: datetime) -> bool:
        if isinstance(start, datetime):
            return start < now
        return start < now.date()

    def _editable_vevent(self, ical: icalendar.Calendar) -> icalendar.Component:
        """Refuse les cas où une modification aurait des effets inattendus."""
        vevents = list(ical.walk("VEVENT"))
        if len(vevents) != 1 or any(k in vevents[0] for k in ("RRULE", "RDATE", "RECURRENCE-ID")):
            raise ServiceError(
                "Événement récurrent : non modifiable ici (risque de toucher toute la série). "
                "Fais-le dans l'app Calendrier."
            )
        if any(k in vevents[0] for k in ("ATTENDEE", "ORGANIZER")):
            raise ServiceError(
                "Événement avec invités : le modifier enverrait des notifications à d'autres "
                "personnes. Fais-le dans l'app Calendrier."
            )
        return vevents[0]

    def _writable_calendar(self, name: str | None) -> CalendarRef:
        """LE contrôle d'accès en écriture. Toute écriture commence par ici."""
        if not name or not name.strip():
            raise ServiceError("Précise le calendrier : choisis-le d'après son usage (list_calendars).")
        if self.config.is_protected(name):
            raise ServiceError(f"« {name.strip()} » est protégé : lecture seule, aucune modification possible.")
        ref = self._find_calendar(name)
        if not self._can_write(ref):
            allowed = ", ".join(c.name for c in self.backend.list_calendars() if self._can_write(c))
            raise ServiceError(f"« {ref.name} » est en lecture seule. Calendriers modifiables : {allowed}.")
        return ref

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
