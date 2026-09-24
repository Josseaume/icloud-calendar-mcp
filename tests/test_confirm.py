import subprocess
import sys

import pytest

from icloud_calendar_mcp import confirm
from icloud_calendar_mcp.confirm import ask_native_confirmation


def fake_run(returncode, stdout, calls):
    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr="")
    return run


@pytest.fixture(autouse=True)
def on_macos(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")


def test_question_passee_en_argument_jamais_dans_le_script(monkeypatch):
    calls = []
    monkeypatch.setattr(confirm.subprocess, "run", fake_run(0, "Supprimer\n", calls))
    question = 'Titre "piégé" & do shell script "rm -rf ~"'
    assert ask_native_confirmation(question) is True
    args = calls[0]
    assert args[0] == "/usr/bin/osascript"
    assert args[-1] == question  # la question est un argument...
    assert question not in args[2]  # ...et n'apparaît pas dans le code AppleScript


@pytest.mark.parametrize("returncode,stdout", [
    (0, "TIMEOUT\n"),  # personne n'a répondu
    (1, ""),  # clic sur « Annuler »
    (0, "Annuler\n"),
    (0, ""),
])
def test_tout_sauf_supprimer_veut_dire_non(monkeypatch, returncode, stdout):
    monkeypatch.setattr(confirm.subprocess, "run", fake_run(returncode, stdout, []))
    assert ask_native_confirmation("?") is False


def test_hors_macos_non(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert ask_native_confirmation("?") is False


def test_osascript_introuvable_non(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("absent")
    monkeypatch.setattr(confirm.subprocess, "run", boom)
    assert ask_native_confirmation("?") is False
