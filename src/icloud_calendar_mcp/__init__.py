"""Serveur MCP pour l'agenda iCloud (CalDAV).

Deux usages :
  icloud-calendar-mcp          lance le serveur (c'est Claude qui le fait)
  icloud-calendar-mcp check    vérifie config + Trousseau + connexion iCloud
"""

import sys

from .backend import BackendError, CaldavBackend
from .config import ConfigError, config_path, load_config, normalize
from .keychain import KeychainError, read_password


def main() -> None:
    args = sys.argv[1:]
    if args == ["check"]:
        sys.exit(check())
    if args:
        print("Usage : icloud-calendar-mcp [check]", file=sys.stderr)
        sys.exit(2)
    print("Le serveur MCP arrive à l'étape 3. Pour l'instant : icloud-calendar-mcp check", file=sys.stderr)
    sys.exit(2)


def check() -> int:
    """Diagnostic lisible par un humain. N'affiche jamais le mot de passe."""
    try:
        config = load_config()
        print(f"Config    : {config_path()}")
        print(f"Apple ID  : {config.apple_id}")
        password = read_password()
        print("Trousseau : mot de passe trouvé (non affiché)")
        backend = CaldavBackend(config.caldav_url, config.apple_id, lambda: password)
        calendars = backend.list_calendars()
    except (ConfigError, KeychainError, BackendError) as exc:
        print(f"ÉCHEC : {exc}", file=sys.stderr)
        return 1

    print(f"iCloud    : connecté, {len(calendars)} calendrier(s) d'événements")
    default = normalize(config.default_calendar) if config.default_calendar else None
    for cal in sorted(calendars, key=lambda c: normalize(c.name)):
        if config.is_protected(cal.name):
            mode = "PROTÉGÉ (lecture seule)"
        elif config.can_write(cal.name):
            mode = "écriture" + (" (par défaut)" if normalize(cal.name) == default else "")
        else:
            mode = "lecture seule"
        print(f"  - {cal.name:<32} {mode}")

    found = {normalize(c.name) for c in calendars}
    for name in sorted(config.writable_calendars - found):
        print(f"Attention : le calendrier modifiable « {name} » n'existe pas sur iCloud.")
    for name in sorted(config.protected_calendars - found):
        print(f"Info : le calendrier protégé « {name} » n'apparaît pas en CalDAV (abonnement ?).")
    return 0
