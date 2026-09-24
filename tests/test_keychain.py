import subprocess
import sys

import pytest

from icloud_calendar_mcp import keychain
from icloud_calendar_mcp.keychain import KeychainError, read_password

# Faux mot de passe pour les tests (volontairement pas au format Apple).
FAKE = "FAUX-MOT-DE-PASSE-1234"


def fake_run(returncode, stdout="", calls=None):
    def run(args, **kwargs):
        if calls is not None:
            calls.append(args)
        return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr="")

    return run


@pytest.fixture(autouse=True)
def on_macos(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")


def test_lit_le_mot_de_passe_avec_l_outil_systeme(monkeypatch):
    calls = []
    monkeypatch.setattr(keychain.subprocess, "run", fake_run(0, FAKE + "\n", calls))
    assert read_password() == FAKE
    # Chemin absolu vers l'outil d'Apple, recherche par nom de service, -w.
    assert calls == [["/usr/bin/security", "find-generic-password", "-s", "icloud-calendar-mcp", "-w"]]


def test_entree_absente(monkeypatch):
    monkeypatch.setattr(keychain.subprocess, "run", fake_run(44))
    with pytest.raises(KeychainError, match="Aucune entrée"):
        read_password()


def test_acces_refuse(monkeypatch):
    monkeypatch.setattr(keychain.subprocess, "run", fake_run(51))
    with pytest.raises(KeychainError, match="refusé"):
        read_password()


def test_mot_de_passe_vide(monkeypatch):
    monkeypatch.setattr(keychain.subprocess, "run", fake_run(0, "\n"))
    with pytest.raises(KeychainError, match="vide"):
        read_password()


def test_hors_macos(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(KeychainError, match="macOS"):
        read_password()
