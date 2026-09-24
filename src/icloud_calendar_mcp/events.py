"""Traduction entre le format iCalendar (.ics) et des données simples.

Un événement iCloud est un petit fichier texte au format iCalendar (RFC 5545).
Ce module le lit (pour list_events) et l'écrit (pour create/update), et gère
les dates : fuseau horaire, journées entières, affichage en français.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import icalendar

JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre"]

# Les notes sont écrites par n'importe qui (invitations, ADE...) : on les
# tronque dans les listes pour limiter ce qui arrive dans la conversation.
NOTES_PREVIEW = 500


class EventInputError(ValueError):
    """Donnée d'entrée invalide (date mal formée, titre vide...)."""


@dataclass(frozen=True)
class EventInfo:
    calendar: str
    event_id: str
    title: str
    start: datetime | date
    end: datetime | date  # pour une journée entière : dernier jour INCLUS
    all_day: bool
    location: str | None = None
    notes: str | None = None
    recurring: bool = False
    has_attendees: bool = False

    def to_dict(self) -> dict:
        data = {
            "calendar": self.calendar,
            "event_id": self.event_id,
            "title": self.title,
            "when": describe_when(self.start, self.end, self.all_day),
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "all_day": self.all_day,
        }
        if self.location:
            data["location"] = self.location
        if self.notes:
            data["notes"] = self.notes[:NOTES_PREVIEW] + ("…" if len(self.notes) > NOTES_PREVIEW else "")
        if self.recurring:
            data["recurring"] = True
        if self.has_attendees:
            data["has_attendees"] = True
        return data

    def sort_key(self) -> tuple:
        """Tri chronologique : par jour, journées entières en premier, puis par heure."""
        if self.all_day:
            return (self.start, 0, 0.0)
        return (self.start.date(), 1, self.start.timestamp())


# --- lecture ------------------------------------------------------------------


def from_component(comp: icalendar.Component, calendar: str, event_id: str, tz: ZoneInfo) -> EventInfo:
    """Transforme un VEVENT iCalendar en EventInfo, heures ramenées dans `tz`."""
    start = comp.decoded("DTSTART")
    # Attention : en Python, un datetime EST AUSSI une date. On teste donc datetime.
    all_day = not isinstance(start, datetime)

    if "DTEND" in comp:
        end = comp.decoded("DTEND")
    elif "DURATION" in comp:
        end = start + comp.decoded("DURATION")
    else:
        end = start + timedelta(days=1) if all_day else start

    if all_day:
        # En iCalendar, la fin d'une journée entière est EXCLUE (lendemain) :
        # on la ramène au dernier jour inclus, plus naturel.
        end = max(start, end - timedelta(days=1))
    else:
        start, end = to_local(start, tz), to_local(end, tz)

    return EventInfo(
        calendar=calendar,
        event_id=event_id,
        title=_text(comp, "SUMMARY") or "(sans titre)",
        start=start,
        end=end,
        all_day=all_day,
        location=_text(comp, "LOCATION"),
        notes=_text(comp, "DESCRIPTION"),
        recurring=any(key in comp for key in ("RRULE", "RDATE", "RECURRENCE-ID")),
        has_attendees=any(key in comp for key in ("ATTENDEE", "ORGANIZER")),
    )


def _text(comp: icalendar.Component, key: str) -> str | None:
    value = comp.get(key)
    if value is None:
        return None
    return str(value).strip() or None


def to_local(value: datetime, tz: ZoneInfo) -> datetime:
    """Heure « flottante » (sans fuseau) : on la considère locale. Sinon on convertit."""
    if value.tzinfo is None:
        return value.replace(tzinfo=tz)
    return value.astimezone(tz)


# --- dates saisies par Claude -------------------------------------------------


def parse_when(value: str, tz: ZoneInfo) -> datetime | date:
    """Lit une date ISO : « 2026-09-28 » (journée) ou « 2026-09-28T18:00 » (heure).

    Sans fuseau précisé, l'heure est comprise dans le fuseau de la config.
    """
    text = value.strip()
    try:
        if len(text) == 10:
            return date.fromisoformat(text)
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise EventInputError(
            f"Date illisible : {value!r}. Format attendu : 2026-09-28 ou 2026-09-28T18:00."
        ) from None
    return to_local(parsed, tz)


def range_bounds(start: str, end: str, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """Bornes d'une recherche. Une date seule en fin de période compte en entier."""
    start_value, end_value = parse_when(start, tz), parse_when(end, tz)
    if not isinstance(start_value, datetime):
        start_value = datetime.combine(start_value, time.min, tzinfo=tz)
    if not isinstance(end_value, datetime):
        end_value = datetime.combine(end_value + timedelta(days=1), time.min, tzinfo=tz)
    if end_value <= start_value:
        raise EventInputError("La fin de la période doit être après le début.")
    return start_value, end_value


# --- affichage en français ------------------------------------------------------


def describe_day(day: date) -> str:
    return f"{JOURS[day.weekday()]} {day.day} {MOIS[day.month - 1]} {day.year}"


def describe_period(start: datetime, end: datetime) -> str:
    """Période de recherche : « lundi 28 septembre 2026 » si ce sont des jours entiers."""
    if start.time() == time.min and end.time() == time.min:
        last = (end - timedelta(days=1)).date()
        if last == start.date():
            return describe_day(last)
        return f"du {describe_day(start.date())} au {describe_day(last)}"
    return describe_when(start, end, all_day=False)


def describe_when(start: datetime | date, end: datetime | date, all_day: bool) -> str:
    """« lundi 28 septembre 2026, 18:00 – 19:30 » : jour de la semaine toujours écrit,
    pour qu'une erreur de date saute aux yeux."""
    if all_day:
        if end == start:
            return f"{describe_day(start)} (journée entière)"
        return f"du {describe_day(start)} au {describe_day(end)} (journées entières)"
    if start.date() == end.date():
        return f"{describe_day(start)}, {start:%H:%M} – {end:%H:%M}"
    return f"du {describe_day(start)} {start:%H:%M} au {describe_day(end)} {end:%H:%M}"


# --- écriture -------------------------------------------------------------------

PRODID = "-//Arthur//icloud-calendar-mcp//FR"
TITLE_MAX, LOCATION_MAX, NOTES_MAX = 200, 300, 4000
MAX_DURATION = timedelta(days=14)
ALERT_MAX_MINUTES = 7 * 24 * 60


def clean_text(value: str | None, field: str, max_len: int, multiline: bool = False) -> str | None:
    """Nettoie un texte venant de Claude avant de l'écrire dans iCloud.

    On retire les caractères de contrôle invisibles (sauf les retours à la
    ligne des notes) : ils n'ont rien à faire dans un agenda et servent
    parfois à cacher des choses.
    """
    if value is None:
        return None
    allowed = "\n\t" if multiline else "\t"
    text = "".join(
        ch for ch in value.replace("\r\n", "\n")
        if ch.isprintable() or ch in allowed
    ).strip()
    if not multiline:
        text = " ".join(text.split())
    if len(text) > max_len:
        raise EventInputError(f"{field} trop long ({max_len} caractères maximum).")
    return text


def event_times(start: str, end: str | None, all_day: bool, tz: ZoneInfo) -> tuple[datetime | date, datetime | date]:
    """Valide début/fin d'un événement. Pour une journée entière, `end` = dernier jour inclus."""
    start_value = parse_when(start, tz)
    end_value = parse_when(end, tz) if end else None

    if all_day:
        start_day = start_value.date() if isinstance(start_value, datetime) else start_value
        end_day = end_value.date() if isinstance(end_value, datetime) else (end_value or start_day)
        if end_day < start_day:
            raise EventInputError("Le dernier jour doit être le même jour ou après le premier.")
        if end_day - start_day > MAX_DURATION:
            raise EventInputError("Durée trop longue (14 jours maximum).")
        return start_day, end_day

    if not isinstance(start_value, datetime) or (end_value is not None and not isinstance(end_value, datetime)):
        raise EventInputError("Donne une heure (2026-09-28T18:00), ou all_day=true pour une journée entière.")
    if end_value is None:
        raise EventInputError("Donne l'heure de fin (end) : c'est obligatoire pour un événement avec horaire.")
    check_duration(start_value, end_value)
    return start_value, end_value


def check_duration(start: datetime, end: datetime) -> None:
    if end <= start:
        raise EventInputError("La fin doit être après le début.")
    if end - start > MAX_DURATION:
        raise EventInputError("Durée trop longue (14 jours maximum) : vérifie les dates.")


def build_ical(*, uid: str, title: str, start: datetime | date, end: datetime | date, all_day: bool,
               location: str | None, notes: str | None, alert_minutes: int | None, now: datetime) -> str:
    """Fabrique le fichier .ics d'un nouvel événement.

    C'est la bibliothèque icalendar qui écrit le texte : elle échappe les
    retours à la ligne et les « ; », donc un titre piégé ne peut pas ajouter
    de ligne (par exemple un invité) dans le fichier.
    """
    if alert_minutes is not None and not 0 <= alert_minutes <= ALERT_MAX_MINUTES:
        raise EventInputError("Rappel : entre 0 et 10080 minutes (une semaine) avant le début.")

    event = icalendar.Event()
    event.add("uid", uid)
    for key in ("dtstamp", "created", "last-modified"):
        event.add(key, now)
    event.add("summary", title)
    event.add("dtstart", start)
    # En iCalendar, la fin d'une journée entière est le lendemain (exclu).
    event.add("dtend", end + timedelta(days=1) if all_day else end)
    if location:
        event.add("location", location)
    if notes:
        event.add("description", notes)
    if alert_minutes is not None:
        event.add_component(make_alarm(alert_minutes))

    cal = icalendar.Calendar()
    cal.add("prodid", PRODID)
    cal.add("version", "2.0")
    cal.add_component(event)
    # Ajoute la définition du fuseau Europe/Paris (heure d'été/hiver) dans le
    # fichier, comme l'exige la norme : l'iPhone affiche alors la bonne heure.
    cal.add_missing_timezones()
    return cal.to_ical().decode()


def make_alarm(minutes: int) -> icalendar.Alarm:
    """Notification « N minutes avant », au format attendu par Calendrier."""
    alarm = icalendar.Alarm()
    alarm_uid = str(uuid.uuid4()).upper()
    alarm.add("uid", alarm_uid)
    alarm.add("x-wr-alarmuid", alarm_uid)
    alarm.add("action", "DISPLAY")
    alarm.add("description", "Rappel")
    alarm.add("trigger", timedelta(minutes=-minutes))
    return alarm


def replace_prop(comp: icalendar.Component, key: str, value) -> None:
    comp.pop(key, None)
    if value is not None and value != "":
        comp.add(key.lower(), value)
