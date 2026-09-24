"""Configuration du serveur. Elle ne contient aucun secret.

Elle vit hors du dépôt Git, dans ~/.config/icloud-calendar-mcp/config.toml
(chemin modifiable avec la variable d'environnement ICLOUD_CALENDAR_MCP_CONFIG).
"""

import os
import tomllib
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_PATH = Path.home() / ".config" / "icloud-calendar-mcp" / "config.toml"
ICLOUD_CALDAV_URL = "https://caldav.icloud.com/"

# Si une clé de la config contient un de ces mots, on refuse de démarrer :
# un secret n'a rien à faire dans un fichier texte.
_SECRET_WORDS = ("pass", "secret", "token", "mdp")


class ConfigError(ValueError):
    """La configuration est absente ou incohérente."""


def normalize(name: str) -> str:
    """Forme canonique d'un nom de calendrier, pour comparer sans piège.

    NFC : un « é » peut s'écrire de deux façons en Unicode, on les unifie.
    casefold : « Cours ESIEE » et « cours esiee » désignent le même calendrier.
    """
    return unicodedata.normalize("NFC", name).strip().casefold()


@dataclass(frozen=True)
class Config:
    apple_id: str
    timezone: ZoneInfo
    writable_calendars: frozenset[str]  # noms normalisés
    protected_calendars: frozenset[str]  # noms normalisés
    default_calendar: str | None  # nom tel qu'écrit dans la config
    caldav_url: str = ICLOUD_CALDAV_URL

    def is_protected(self, calendar_name: str) -> bool:
        return normalize(calendar_name) in self.protected_calendars

    def can_write(self, calendar_name: str) -> bool:
        """Liste blanche : on n'écrit QUE dans les calendriers listés.

        Un calendrier protégé reste en lecture seule même s'il est listé.
        """
        name = normalize(calendar_name)
        return name in self.writable_calendars and name not in self.protected_calendars


def config_path() -> Path:
    return Path(os.environ.get("ICLOUD_CALENDAR_MCP_CONFIG", DEFAULT_PATH)).expanduser()


def load_config(path: Path | None = None) -> Config:
    path = path or config_path()
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(
            f"Config introuvable : {path}. Copie config.example.toml à cet endroit."
        ) from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Config illisible ({path}) : {exc}") from None
    return parse_config(raw)


def parse_config(raw: dict) -> Config:
    for key in raw:
        if any(word in key.lower() for word in _SECRET_WORDS):
            raise ConfigError(
                f"Clé « {key} » refusée : aucun secret dans la config, "
                "le mot de passe va dans le Trousseau."
            )

    apple_id = raw.get("apple_id")
    if not isinstance(apple_id, str) or "@" not in apple_id:
        raise ConfigError("apple_id manquant ou invalide (attendu : l'email du compte Apple).")

    tz_name = raw.get("timezone", "Europe/Paris")
    try:
        timezone = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ConfigError(f"Fuseau horaire inconnu : {tz_name!r}") from None

    writable = _name_list(raw, "writable_calendars")
    protected = _name_list(raw, "protected_calendars")
    both = writable & protected
    if both:
        raise ConfigError(
            f"Calendrier(s) à la fois modifiable(s) et protégé(s) : {sorted(both)}. "
            "Retire-les de writable_calendars."
        )

    default = raw.get("default_calendar")
    if default is not None:
        if not isinstance(default, str) or normalize(default) not in writable:
            raise ConfigError("default_calendar doit faire partie de writable_calendars.")

    return Config(
        apple_id=apple_id.strip(),
        timezone=timezone,
        writable_calendars=writable,
        protected_calendars=protected,
        default_calendar=default,
    )


def _name_list(raw: dict, key: str) -> frozenset[str]:
    value = raw.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise ConfigError(f"{key} doit être une liste de noms de calendriers.")
    return frozenset(normalize(v) for v in value)
