import json

import pytest

from icloud_calendar_mcp.events import EventInputError
from icloud_calendar_mcp.service import ServiceError, describe_color, parse_color


def test_creer_un_calendrier_puis_y_ecrire(service, backend, created):
    result = service.create_calendar("Sport", "vert", "séances de sport")
    assert result["created_calendar"] == {"name": "Sport", "writable": True, "color": "#63DA38FF",
                                          "usage": "séances de sport"}
    # Créé par Claude => modifiable, sans toucher à la config.
    service.create_event("Sport", "Basic Fit", "2026-09-28T18:00", "2026-09-28T19:30")
    cals = {c["name"]: c for c in service.list_calendars()}
    assert cals["Sport"]["writable"] is True and cals["Sport"]["usage"] == "séances de sport"


def test_la_memoire_survit_au_redemarrage(service, created):
    service.create_calendar("Sport")
    data = json.loads(created.path.read_text())
    assert [v["name"] for v in data.values()] == ["Sport"]
    assert oct(created.path.stat().st_mode & 0o777) == "0o600"


def test_nom_protege_refuse(service, backend):
    with pytest.raises(ServiceError, match="protégé"):
        service.create_calendar("cours esiee")
    assert backend.writes == []


def test_nom_existant_refuse(service, backend):
    with pytest.raises(ServiceError, match="existe déjà"):
        service.create_calendar("perso")
    assert backend.writes == []


def test_limite_anti_emballement(service, backend):
    for i in range(10):
        service.create_calendar(f"Cal {i}")
    with pytest.raises(ServiceError, match="Limite"):
        service.create_calendar("Un de trop")


def test_couleur_calendrier_modifiable(service, backend):
    assert service.set_calendar_color("Perso", "violet") == {"calendar": "Perso", "color": "violet"}
    assert backend.writes == [("set_color", "Perso", "#CC73E1FF")]


def test_couleur_refusee_sur_cours_esiee(service, backend):
    with pytest.raises(ServiceError, match="protégé"):
        service.set_calendar_color("Cours ESIEE", "rouge")
    assert backend.writes == []


def test_couleur_permise_sur_un_calendrier_en_lecture_seule(service, backend):
    """Bug remonté par Arthur : « Autre » est en lecture seule, mais sa couleur
    n'est qu'un réglage d'affichage. Ses événements, eux, restent protégés."""
    assert service.set_calendar_color("Autre", "marron")["color"] == "marron"
    with pytest.raises(ServiceError, match="lecture seule"):
        service.create_event("Autre", "x", "2026-09-28T18:00", "2026-09-28T19:00")
    assert backend.writes == [("set_color", "Autre", "#A2845EFF")]


def test_couleur_visible_dans_la_liste(service, backend):
    """Bug remonté par Arthur : Claude ne pouvait pas savoir lequel est « le orange »."""
    autre = next(c for c in backend.calendars if c.name == "Autre")
    backend.colors[autre.url] = "#FF9500FF"
    cals = {c["name"]: c for c in service.list_calendars()}
    assert cals["Autre"]["color"] == "orange"
    assert cals["Perso"]["color"] == "bleu"


@pytest.mark.parametrize("code,expected", [
    ("#FF9500FF", "orange"),
    ("#EB512EFF", "#EB512E (proche de rouge)"),
    ("#83D754FF", "#83D754 (proche de vert)"),
])
def test_describe_color(code, expected):
    assert describe_color(code) == expected


def test_fichier_memoire_ne_rend_pas_esiee_modifiable(service, backend, created):
    """Même si l'adresse de Cours ESIEE se retrouvait dans le fichier mémoire,
    la protection gagne."""
    esiee = next(c for c in backend.calendars if c.name == "Cours ESIEE")
    created.add(esiee.url, "Cours ESIEE", None)
    with pytest.raises(ServiceError, match="protégé"):
        service.create_event("Cours ESIEE", "x", "2026-09-28T18:00", "2026-09-28T19:00")


@pytest.mark.parametrize("value,expected", [("Vert", "#63DA38FF"), ("#1badf8", "#1BADF8FF"), ("1BADF8", "#1BADF8FF")])
def test_parse_color(value, expected):
    assert parse_color(value) == expected


def test_couleur_inconnue():
    with pytest.raises(EventInputError, match="Couleur inconnue"):
        parse_color("fuchsia fluo")


def test_reconnu_meme_si_icloud_change_de_serveur(created):
    """Bug vu en vrai : même calendrier, adresse différente selon la session."""
    created.add("https://p130-caldav.icloud.com:443/123/calendars/abc/", "Sport", None)
    assert created.contains("https://caldav.icloud.com/123/calendars/abc/")
    assert not created.contains("https://caldav.icloud.com/123/calendars/autre/")
