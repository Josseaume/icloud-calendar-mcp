import icalendar
import pytest

from conftest import at, make_ics
from icloud_calendar_mcp.backend import BackendError
from icloud_calendar_mcp.events import EventInputError
from icloud_calendar_mcp.service import ServiceError


def vevent_of(backend, calendar, event_id):
    return icalendar.Calendar.from_ical(backend.ics(calendar, event_id)).walk("VEVENT")[0]


# --- création ---------------------------------------------------------------------


def test_creation_basic_fit(service, backend):
    result = service.create_event("Perso", "Basic Fit", "2026-09-28T18:00", "2026-09-28T19:30")
    created = result["created"]
    assert created["when"] == "lundi 28 septembre 2026, 18:00 – 19:30"
    assert created["calendar"] == "Perso"
    ics = backend.ics("Perso", created["event_id"])
    assert "DTSTART;TZID=Europe/Paris:20260928T180000" in ics
    assert "BEGIN:VTIMEZONE" in ics  # définition du fuseau incluse
    assert "conflicts" not in result and "warning" not in result


def test_creation_refusee_dans_cours_esiee(service, backend):
    with pytest.raises(ServiceError, match="protégé"):
        service.create_event("Cours ESIEE", "Pirate", "2026-09-28T18:00", "2026-09-28T19:00")
    assert backend.writes == []  # rien n'a été écrit


def test_protection_insensible_a_la_casse(service, backend):
    with pytest.raises(ServiceError, match="protégé"):
        service.create_event("  cours esiee ", "Pirate", "2026-09-28T18:00", "2026-09-28T19:00")
    assert backend.writes == []


def test_creation_refusee_hors_liste_blanche(service, backend):
    with pytest.raises(ServiceError, match="lecture seule"):
        service.create_event("Autre", "x", "2026-09-28T18:00", "2026-09-28T19:00")
    assert backend.writes == []


def test_calendrier_obligatoire(service):
    with pytest.raises(ServiceError, match="Précise le calendrier"):
        service.create_event("", "x", "2026-09-28T18:00", "2026-09-28T19:00")


def test_titre_piege_ne_peut_pas_ajouter_d_invite(service, backend):
    """Injection iCalendar : un titre contenant un retour à la ligne ne doit pas
    pouvoir fabriquer une nouvelle ligne ATTENDEE (un invité) dans le fichier."""
    title = "Sport\r\nATTENDEE:mailto:pirate@exemple.com"
    created = service.create_event("Perso", title, "2026-09-28T18:00", "2026-09-28T19:00")["created"]
    ics = backend.ics("Perso", created["event_id"])
    assert "\nATTENDEE" not in ics
    assert "ATTENDEE" not in vevent_of(backend, "Perso", created["event_id"])


def test_notes_multilignes_conservees_sans_injection(service, backend):
    notes = "Ligne 1\nORGANIZER:mailto:pirate@exemple.com"
    created = service.create_event("Perso", "x", "2026-09-28T18:00", "2026-09-28T19:00", notes=notes)["created"]
    vevent = vevent_of(backend, "Perso", created["event_id"])
    assert "ORGANIZER" not in vevent
    assert str(vevent["DESCRIPTION"]) == notes


def test_chevauchement_signale(service, backend, paris):
    backend.add("Cours ESIEE", "c.ics", make_ics("c", "Pentest", at(paris, 2026, 9, 28, 17), at(paris, 2026, 9, 28, 18, 30)))
    result = service.create_event("Perso", "Basic Fit", "2026-09-28T18:00", "2026-09-28T19:30")
    assert result["conflicts"] == [{"calendar": "Cours ESIEE", "title": "Pentest",
                                    "when": "lundi 28 septembre 2026, 17:00 – 18:30"}]


def test_evenement_dans_le_passe_signale(service):
    result = service.create_event("Perso", "x", "2026-09-01T18:00", "2026-09-01T19:00")
    assert "passé" in result["warning"]


def test_journee_entiere(service, backend):
    created = service.create_event("Perso", "Vacances", "2026-10-24", "2026-10-26", all_day=True)["created"]
    vevent = vevent_of(backend, "Perso", created["event_id"])
    assert str(vevent.decoded("DTEND")) == "2026-10-27"  # lendemain exclu, norme iCalendar
    assert created["when"] == "du samedi 24 octobre 2026 au lundi 26 octobre 2026 (journées entières)"


def test_rappel(service, backend):
    created = service.create_event("Perso", "RDV", "2026-09-28T09:00", "2026-09-28T10:00",
                                   alert_minutes_before=30)["created"]
    alarm = vevent_of(backend, "Perso", created["event_id"]).walk("VALARM")[0]
    assert alarm["TRIGGER"].to_ical() == b"-PT30M"


@pytest.mark.parametrize("start,end,message", [
    ("2026-09-28T18:00", None, "fin"),
    ("2026-09-28T18:00", "2026-09-28T17:00", "après le début"),
    ("2026-09-28", "2026-09-28T19:00", "heure"),
    ("2026-09-28T18:00", "2026-10-28T19:00", "trop longue"),
])
def test_horaires_invalides(service, backend, start, end, message):
    with pytest.raises(EventInputError, match=message):
        service.create_event("Perso", "x", start, end)
    assert backend.writes == []


# --- modification ---------------------------------------------------------------


@pytest.fixture
def basic_fit(service):
    return service.create_event("Perso", "Basic Fit", "2026-09-28T18:00", "2026-09-28T19:30")["created"]


def test_modifier_le_titre(service, basic_fit):
    updated = service.update_event("Perso", basic_fit["event_id"], title="Basic Fit jambes")["updated"]
    assert updated["title"] == "Basic Fit jambes"
    assert updated["when"] == basic_fit["when"]


def test_deplacer_garde_la_duree(service, basic_fit):
    updated = service.update_event("Perso", basic_fit["event_id"], start="2026-09-29T19:00")["updated"]
    assert updated["when"] == "mardi 29 septembre 2026, 19:00 – 20:30"


def test_supprimer_le_lieu(service, backend):
    created = service.create_event("Perso", "x", "2026-09-28T18:00", "2026-09-28T19:00", location="Salle")["created"]
    updated = service.update_event("Perso", created["event_id"], location="")["updated"]
    assert "location" not in updated


def test_modification_refusee_dans_cours_esiee(service, backend, paris):
    backend.add("Cours ESIEE", "c.ics", make_ics("c", "Pentest", at(paris, 2026, 9, 28, 17), at(paris, 2026, 9, 28, 18)))
    with pytest.raises(ServiceError, match="protégé"):
        service.update_event("Cours ESIEE", "c.ics", title="Annulé")
    assert backend.writes == []


def test_path_traversal_refuse(service, backend):
    """Un event_id comme « ../1/c.ics » ne doit pas permettre de sortir du
    calendrier autorisé pour atteindre un autre calendrier."""
    with pytest.raises(BackendError, match="event_id invalide"):
        service.update_event("Perso", "../2/c.ics", title="x")
    assert backend.writes == []


def test_evenement_recurrent_refuse(service, backend, paris):
    backend.add("Perso", "r.ics", make_ics("r", "Hebdo", at(paris, 2026, 9, 28, 8), at(paris, 2026, 9, 28, 9),
                                         rrule={"freq": "weekly"}))
    with pytest.raises(ServiceError, match="récurrent"):
        service.update_event("Perso", "r.ics", title="x")
    assert backend.writes == []


def test_evenement_avec_invites_refuse(service, backend, paris):
    backend.add("Perso", "i.ics", make_ics("i", "Réunion", at(paris, 2026, 9, 28, 8), at(paris, 2026, 9, 28, 9),
                                         attendee="mailto:collegue@exemple.com"))
    with pytest.raises(ServiceError, match="invités"):
        service.update_event("Perso", "i.ics", title="x")
    assert backend.writes == []


def test_rien_a_modifier(service, basic_fit):
    with pytest.raises(EventInputError, match="Rien à modifier"):
        service.update_event("Perso", basic_fit["event_id"])


def test_journee_entiere_vers_horaire_refuse(service):
    created = service.create_event("Perso", "Off", "2026-10-02", all_day=True)["created"]
    with pytest.raises(EventInputError, match="journée entière"):
        service.update_event("Perso", created["event_id"], start="2026-10-02T10:00")
