import pytest

from conftest import FakeBackend, at, make_ics
from icloud_calendar_mcp.service import CalendarService, ServiceError


def test_list_calendars_indique_droits_et_usage(service):
    cals = {c["name"]: c for c in service.list_calendars()}
    assert cals["Perso"] == {"name": "Perso", "writable": True, "usage": "sport et vie perso"}
    assert cals["Cours ESIEE"]["writable"] is False
    assert cals["Cours ESIEE"]["protected"] is True
    assert cals["Autre"]["writable"] is False


def test_list_events_tous_calendriers_tries(service, backend, paris):
    backend.add("Perso", "b.ics", make_ics("b", "Basic Fit", at(paris, 2026, 9, 28, 18), at(paris, 2026, 9, 28, 19, 30)))
    backend.add("Cours ESIEE", "a.ics", make_ics("a", "Réseaux", at(paris, 2026, 9, 28, 8), at(paris, 2026, 9, 28, 10)))
    backend.add("Perso", "c.ics", make_ics("c", "Hors période", at(paris, 2026, 10, 5, 8), at(paris, 2026, 10, 5, 9)))

    result = service.list_events("2026-09-28", "2026-09-28")
    assert result["count"] == 2
    assert [e["title"] for e in result["events"]] == ["Réseaux", "Basic Fit"]
    assert result["events"][0]["calendar"] == "Cours ESIEE"


def test_list_events_un_calendrier(service, backend, paris):
    backend.add("Perso", "b.ics", make_ics("b", "Basic Fit", at(paris, 2026, 9, 28, 18), at(paris, 2026, 9, 28, 19)))
    backend.add("Travaille", "t.ics", make_ics("t", "Projet", at(paris, 2026, 9, 28, 14), at(paris, 2026, 9, 28, 15)))
    result = service.list_events("2026-09-28", "2026-09-28", calendar="perso")
    assert [e["title"] for e in result["events"]] == ["Basic Fit"]


def test_calendrier_inconnu(service):
    with pytest.raises(ServiceError, match="introuvable"):
        service.list_events("2026-09-28", "2026-09-29", calendar="Vacances")


def test_periode_trop_longue(service):
    with pytest.raises(ServiceError, match="3 mois"):
        service.list_events("2026-09-01", "2027-01-31")


def test_deux_calendriers_de_meme_nom_refuses(config, created):
    service = CalendarService(FakeBackend(["Perso", "perso"]), config, created)
    with pytest.raises(ServiceError, match="Plusieurs"):
        service.list_events("2026-09-28", "2026-09-29", calendar="Perso")
