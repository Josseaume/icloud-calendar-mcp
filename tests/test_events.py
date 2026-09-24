from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import icalendar
import pytest

from icloud_calendar_mcp.events import (
    EventInputError,
    describe_when,
    from_component,
    parse_when,
    range_bounds,
)

PARIS = ZoneInfo("Europe/Paris")


def vevent(**props):
    event = icalendar.Event()
    for key, value in props.items():
        event.add(key.replace("_", "-"), value)
    return event


def test_heure_en_utc_ramenee_a_paris():
    comp = vevent(summary="Basic Fit",
                  dtstart=datetime(2026, 9, 28, 16, 0, tzinfo=timezone.utc),
                  dtend=datetime(2026, 9, 28, 17, 30, tzinfo=timezone.utc))
    info = from_component(comp, "Perso", "abc.ics", PARIS)
    assert info.start.isoformat() == "2026-09-28T18:00:00+02:00"
    assert info.to_dict()["when"] == "lundi 28 septembre 2026, 18:00 – 19:30"


def test_heure_flottante_comprise_comme_locale():
    comp = vevent(summary="x", dtstart=datetime(2026, 12, 1, 9, 0), dtend=datetime(2026, 12, 1, 10, 0))
    info = from_component(comp, "Perso", "a.ics", PARIS)
    assert info.start.isoformat() == "2026-12-01T09:00:00+01:00"  # heure d'hiver


def test_journee_entiere_fin_ramenee_au_dernier_jour_inclus():
    comp = vevent(summary="Vacances", dtstart=date(2026, 10, 24), dtend=date(2026, 10, 27))
    info = from_component(comp, "Perso", "a.ics", PARIS)
    assert info.all_day
    assert info.end == date(2026, 10, 26)
    assert info.to_dict()["when"] == "du samedi 24 octobre 2026 au lundi 26 octobre 2026 (journées entières)"


def test_une_seule_journee():
    comp = vevent(summary="Férié", dtstart=date(2026, 11, 11), dtend=date(2026, 11, 12))
    assert from_component(comp, "Perso", "a.ics", PARIS).to_dict()["when"] == \
        "mercredi 11 novembre 2026 (journée entière)"


def test_duree_au_lieu_de_fin():
    comp = vevent(summary="x", dtstart=datetime(2026, 9, 28, 8, 0, tzinfo=PARIS), duration=timedelta(hours=2))
    assert from_component(comp, "Perso", "a.ics", PARIS).end.hour == 10


def test_recurrence_et_invites_signales():
    comp = vevent(summary="Réunion", dtstart=datetime(2026, 9, 28, 8, 0, tzinfo=PARIS),
                  dtend=datetime(2026, 9, 28, 9, 0, tzinfo=PARIS),
                  rrule={"freq": "weekly"}, attendee="mailto:quelquun@exemple.com")
    data = from_component(comp, "Perso", "a.ics", PARIS).to_dict()
    assert data["recurring"] is True
    assert data["has_attendees"] is True


def test_notes_longues_tronquees():
    comp = vevent(summary="x", dtstart=date(2026, 9, 28), description="a" * 2000)
    assert len(from_component(comp, "Perso", "a.ics", PARIS).to_dict()["notes"]) == 501


def test_parse_when():
    assert parse_when("2026-09-28", PARIS) == date(2026, 9, 28)
    assert parse_when("2026-09-28T18:00", PARIS) == datetime(2026, 9, 28, 18, 0, tzinfo=PARIS)
    assert parse_when("2026-09-28T16:00Z", PARIS).hour == 18
    with pytest.raises(EventInputError, match="illisible"):
        parse_when("lundi prochain", PARIS)


def test_range_bounds_date_de_fin_incluse():
    start, end = range_bounds("2026-09-28", "2026-09-28", PARIS)
    assert end - start == timedelta(days=1)
    with pytest.raises(EventInputError):
        range_bounds("2026-09-29", "2026-09-28", PARIS)


def test_changement_d_heure_affiche_correctement():
    start = datetime(2026, 10, 25, 1, 30, tzinfo=PARIS)
    end = datetime(2026, 10, 25, 3, 30, tzinfo=PARIS)
    assert describe_when(start, end, all_day=False) == "dimanche 25 octobre 2026, 01:30 – 03:30"
