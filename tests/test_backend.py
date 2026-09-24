import niquests

from icloud_calendar_mcp import backend as backend_module
from icloud_calendar_mcp.backend import CaldavBackend


class FakeDAVClient:
    def __init__(self, **kwargs):
        self.session = None

    def principal(self):
        return object()


def test_pas_de_http3(monkeypatch):
    """Bug vu en vrai : en HTTP/3 (UDP), une connexion inactive coupée par le
    réseau faisait attendre 30 s puis échouer. On force une session TCP."""
    monkeypatch.setattr(backend_module.caldav, "DAVClient", FakeDAVClient)
    backend = CaldavBackend("https://exemple.invalid/", "moi@exemple.com", lambda: "FAUX-MDP")
    backend._get_principal()
    assert isinstance(backend._client.session, niquests.Session)
    assert backend._client.session._disable_http3 is True
