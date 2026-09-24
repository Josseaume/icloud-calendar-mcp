"""Faux iCloud en mémoire, pour tester toutes les règles sans réseau."""

from datetime import date, datetime, time, timedelta

import icalendar
import pytest

from icloud_calendar_mcp.backend import BackendError, CalendarRef
from icloud_calendar_mcp.config import parse_config
from icloud_calendar_mcp.service import CalendarService

CONFIG = {
    "apple_id": "prenom.nom@exemple.com",
    "writable_calendars": ["Perso", "Travaille"],
    "protected_calendars": ["Cours ESIEE"],
    "usages": {"Perso": "sport et vie perso"},
}


def make_ics(uid, summary, start, end, **extra) -> str:
    cal = icalendar.Calendar()
    cal.add("prodid", "-//tests//FR")
    cal.add("version", "2.0")
    event = icalendar.Event()
    event.add("uid", uid)
    event.add("summary", summary)
    event.add("dtstart", start)
    event.add("dtend", end)
    for key, value in extra.items():
        event.add(key.replace("_", "-"), value)
    cal.add_component(event)
    return cal.to_ical().decode()


class FakeBackend:
    def __init__(self, names):
        self.calendars = [CalendarRef(name=n, url=f"https://fake/{i}/") for i, n in enumerate(names)]
        self.store: dict[str, dict[str, str]] = {c.url: {} for c in self.calendars}
        self.writes: list[tuple] = []  # journal de toutes les écritures

    def add(self, calendar_name, event_id, ics):
        ref = next(c for c in self.calendars if c.name == calendar_name)
        self.store[ref.url][event_id] = ics

    def list_calendars(self):
        return list(self.calendars)

    def search(self, ref, start, end):
        pairs = []
        for event_id, ics in self.store[ref.url].items():
            for comp in icalendar.Calendar.from_ical(ics).walk("VEVENT"):
                if _overlaps(comp, start, end):
                    pairs.append((event_id, comp))
        return pairs

    def _ref(self, ref):
        if ref.url not in self.store:
            raise BackendError("calendrier inconnu")
        return self.store[ref.url]


def _as_datetime(value, tz):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=tz)
    return datetime.combine(value, time.min, tzinfo=tz)


def _overlaps(comp, start, end):
    tz = start.tzinfo
    ev_start = _as_datetime(comp.decoded("DTSTART"), tz)
    ev_end = _as_datetime(comp.decoded("DTEND"), tz) if "DTEND" in comp else ev_start + timedelta(minutes=1)
    return ev_start < end and ev_end > start


@pytest.fixture
def config():
    return parse_config(CONFIG)


@pytest.fixture
def backend():
    return FakeBackend(["Perso", "Travaille", "Cours ESIEE", "Autre"])


@pytest.fixture
def service(backend, config):
    return CalendarService(backend, config)


@pytest.fixture
def paris(config):
    return config.timezone


def at(paris, y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=paris)


__all__ = ["FakeBackend", "make_ics", "at", "date"]
