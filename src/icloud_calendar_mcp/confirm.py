"""Confirmation par une fenêtre macOS, cliquable seulement par un humain.

Sert quand le client MCP (Claude Desktop, par exemple) ne sait pas poser
lui-même la question à Arthur. Claude ne peut pas cliquer dans cette fenêtre :
la décision vient forcément de toi.
"""

import subprocess
import sys

OSASCRIPT = "/usr/bin/osascript"
TIMEOUT_S = 120
CONFIRM_BUTTON = "Supprimer"

# La question est passée en ARGUMENT (argv) et jamais collée dans le texte du
# script : un titre d'événement piégé (guillemets, commandes AppleScript...)
# reste du texte affiché, il ne peut pas s'exécuter.
# « Annuler » est le bouton par défaut : appuyer sur Entrée n'efface rien.
_SCRIPT = f"""
on run argv
    activate
    set answer to display dialog (item 1 of argv) ¬
        with title "Claude — agenda iCloud" ¬
        buttons {{"Annuler", "{CONFIRM_BUTTON}"}} ¬
        default button "Annuler" cancel button "Annuler" ¬
        with icon caution giving up after {TIMEOUT_S}
    if gave up of answer then return "TIMEOUT"
    return button returned of answer
end run
"""


def ask_native_confirmation(question: str) -> bool:
    """True seulement si Arthur a cliqué « Supprimer ». Tout le reste = non."""
    if sys.platform != "darwin":
        return False
    try:
        result = subprocess.run(
            [OSASCRIPT, "-e", _SCRIPT, question],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S + 30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    # Annuler => osascript sort en erreur (code 1) ; délai dépassé => "TIMEOUT".
    return result.returncode == 0 and result.stdout.strip() == CONFIRM_BUTTON
