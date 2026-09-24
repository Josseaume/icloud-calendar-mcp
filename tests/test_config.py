import pytest

from icloud_calendar_mcp.config import ConfigError, parse_config

BASE = {
    "apple_id": "prenom.nom@exemple.com",
    "writable_calendars": ["Perso"],
    "default_calendar": "Perso",
    "protected_calendars": ["Cours ESIEE"],
}


def test_config_valide():
    config = parse_config(BASE)
    assert config.apple_id == "prenom.nom@exemple.com"
    assert str(config.timezone) == "Europe/Paris"
    assert config.can_write("Perso")


def test_liste_blanche_un_calendrier_non_liste_est_en_lecture_seule():
    config = parse_config(BASE)
    assert not config.can_write("Travail")


def test_comparaison_insensible_a_la_casse_et_aux_espaces():
    config = parse_config(BASE)
    assert config.can_write("  perso ")
    assert config.is_protected("cours esiee")


def test_calendrier_protege_jamais_modifiable():
    config = parse_config(BASE)
    assert config.is_protected("Cours ESIEE")
    assert not config.can_write("Cours ESIEE")


def test_refuse_un_calendrier_a_la_fois_modifiable_et_protege():
    with pytest.raises(ConfigError, match="protégé"):
        parse_config({**BASE, "writable_calendars": ["Perso", "cours esiee"]})


@pytest.mark.parametrize("key", ["password", "app_password", "secret", "token", "mdp"])
def test_refuse_tout_secret_dans_la_config(key):
    with pytest.raises(ConfigError, match="Trousseau"):
        parse_config({**BASE, key: "quelque chose"})


def test_calendrier_par_defaut_doit_etre_modifiable():
    with pytest.raises(ConfigError, match="default_calendar"):
        parse_config({**BASE, "default_calendar": "Travail"})


def test_apple_id_obligatoire():
    with pytest.raises(ConfigError, match="apple_id"):
        parse_config({k: v for k, v in BASE.items() if k != "apple_id"})


def test_fuseau_inconnu():
    with pytest.raises(ConfigError, match="Fuseau"):
        parse_config({**BASE, "timezone": "Mars/Olympus"})
