"""Lecture du mot de passe pour app dans le Trousseau macOS.

Le mot de passe n'est jamais écrit dans un fichier : le serveur le demande au
Trousseau au démarrage et ne le garde qu'en mémoire vive.

On passe par l'outil système `security` (celui qui a créé l'entrée) : comme
c'est lui qui est autorisé sur l'entrée, macOS ne demande rien de plus.
"""

import subprocess
import sys

SERVICE = "icloud-calendar-mcp"

# Chemin absolu : on appelle l'outil d'Apple, et pas un éventuel programme
# nommé « security » placé plus tôt dans le PATH par quelqu'un d'autre.
SECURITY_BIN = "/usr/bin/security"

# Code de retour de `security` quand l'entrée n'existe pas.
_NOT_FOUND = 44


class KeychainError(RuntimeError):
    """Le mot de passe n'a pas pu être lu. Le message ne contient jamais de secret."""


def read_password(service: str = SERVICE) -> str:
    """Renvoie le mot de passe enregistré sous le nom de service `service`."""
    if sys.platform != "darwin":
        raise KeychainError("Le Trousseau n'existe que sur macOS.")
    try:
        # -w : n'écrire que le mot de passe sur la sortie standard, qu'on capture
        # ici sans jamais l'afficher.
        result = subprocess.run(
            [SECURITY_BIN, "find-generic-password", "-s", service, "-w"],
            capture_output=True,
            text=True,
            # Si le Trousseau est verrouillé, macOS ouvre une fenêtre de
            # déverrouillage : on laisse le temps de taper son mot de passe.
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        # `from None` : on n'attache pas l'exception d'origine, pour ne rien
        # faire fuiter d'autre que ce message.
        raise KeychainError("Impossible d'interroger le Trousseau.") from None

    if result.returncode == _NOT_FOUND:
        raise KeychainError(
            f"Aucune entrée « {service} » dans le Trousseau. "
            "Voir la section « Installation » du README."
        )
    if result.returncode != 0:
        raise KeychainError(
            f"Le Trousseau a refusé l'accès à « {service} » (code {result.returncode})."
        )

    password = result.stdout.rstrip("\n")
    if not password:
        raise KeychainError(f"L'entrée « {service} » existe mais son mot de passe est vide.")
    return password
