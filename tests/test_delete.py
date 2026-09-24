"""Suppression : la confirmation doit venir d'Arthur, jamais de Claude."""

import pytest
from mcp import Client
from mcp_types import ElicitResult

from conftest import at, make_ics
from icloud_calendar_mcp.server import build_server

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def basic_fit(backend, paris):
    backend.add("Perso", "bf.ics", make_ics("bf", "Basic Fit", at(paris, 2026, 9, 28, 18), at(paris, 2026, 9, 28, 19, 30)))
    return "bf.ics"


def elicitation(action, garder=None, questions=None):
    """Simule Arthur qui répond dans la fenêtre de Claude Code."""
    async def callback(context, params):
        if questions is not None:
            questions.append(params.message)
        content = None if garder is None else {"garder": garder}
        return ElicitResult(action=action, content=content)
    return callback


def native(answer, questions=None):
    """Simule Arthur qui clique dans la fenêtre macOS."""
    def confirm(question):
        if questions is not None:
            questions.append(question)
        return answer
    return confirm


def no_question(question):
    raise AssertionError("aucune question n'aurait dû être posée à Arthur")


async def delete(service, args, native_confirm=no_question, **client_options):
    async with Client(build_server(service, native_confirm=native_confirm), **client_options) as client:
        return await client.call_tool("delete_event", args)


def still_there(backend, event_id):
    return event_id in backend.store[backend.calendars[0].url]


async def test_claude_ne_peut_pas_fournir_la_confirmation(service):
    async with Client(build_server(service)) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert set(tools["delete_event"].input_schema["properties"]) == {"calendar", "event_id"}
    assert tools["delete_event"].annotations.destructive_hint is True


# « legacy » : ancien protocole (question envoyée pendant l'appel) ;
# « auto » : nouveau protocole 2026 (l'appel est rejoué avec la réponse).
PROTOCOLS = pytest.mark.parametrize("mode", ["auto", "legacy"])


@PROTOCOLS
async def test_accepter_suffit_pour_supprimer(service, backend, basic_fit, mode):
    """Bug vécu par Arthur : il acceptait sans cocher la case, et rien ne se passait.
    Désormais « Accepter » (case laissée décochée, comme renvoyé par Claude Code) supprime."""
    questions = []
    result = await delete(service, {"calendar": "Perso", "event_id": basic_fit}, mode=mode,
                          elicitation_callback=elicitation("accept", False, questions))
    assert not result.is_error
    assert '"deleted": true' in result.content[0].text
    assert not still_there(backend, basic_fit)
    assert "« Basic Fit »" in questions[0]
    assert "lundi 28 septembre 2026, 18:00 – 19:30" in questions[0]
    assert "Accepter = supprimer" in questions[0]


@PROTOCOLS
@pytest.mark.parametrize("action,garder,reason", [
    ("decline", None, "a refusé"),
    ("cancel", None, "sans répondre"),
    ("accept", True, "garder l'événement"),
])
async def test_refus_dans_claude_code(service, backend, basic_fit, action, garder, reason, mode):
    result = await delete(service, {"calendar": "Perso", "event_id": basic_fit}, mode=mode,
                          elicitation_callback=elicitation(action, garder))
    assert '"deleted": false' in result.content[0].text
    assert reason in result.content[0].text  # Claude peut expliquer la vraie cause
    assert still_there(backend, basic_fit)
    assert backend.writes == []


async def test_fenetre_macos_quand_le_client_ne_sait_pas_demander(service, backend, basic_fit):
    questions = []
    result = await delete(service, {"calendar": "Perso", "event_id": basic_fit},
                          native_confirm=native(True, questions))
    assert '"deleted": true' in result.content[0].text
    assert "« Basic Fit »" in questions[0]


async def test_fenetre_macos_refus(service, backend, basic_fit):
    result = await delete(service, {"calendar": "Perso", "event_id": basic_fit}, native_confirm=native(False))
    assert '"deleted": false' in result.content[0].text
    assert "fenêtre macOS" in result.content[0].text
    assert still_there(backend, basic_fit)


async def test_cours_esiee_refuse_sans_meme_poser_la_question(service, backend, paris):
    backend.add("Cours ESIEE", "c.ics", make_ics("c", "Pentest", at(paris, 2026, 9, 28, 8), at(paris, 2026, 9, 28, 10)))
    questions = []
    result = await delete(service, {"calendar": "Cours ESIEE", "event_id": "c.ics"},
                          elicitation_callback=elicitation("accept", False, questions))
    assert result.is_error and "protégé" in result.content[0].text
    assert questions == [] and backend.writes == []


async def test_calendrier_en_lecture_seule_refuse(service, backend):
    result = await delete(service, {"calendar": "Autre", "event_id": "x.ics"})
    assert result.is_error and "lecture seule" in result.content[0].text


async def test_recurrent_refuse(service, backend, paris):
    backend.add("Perso", "r.ics", make_ics("r", "Hebdo", at(paris, 2026, 9, 28, 8), at(paris, 2026, 9, 28, 9),
                                         rrule={"freq": "weekly"}))
    result = await delete(service, {"calendar": "Perso", "event_id": "r.ics"})
    assert result.is_error and "récurrent" in result.content[0].text
    assert backend.writes == []


async def test_path_traversal_refuse(service, backend):
    result = await delete(service, {"calendar": "Perso", "event_id": "../2/c.ics"})
    assert result.is_error and "event_id invalide" in result.content[0].text


async def test_modifie_pendant_la_confirmation_donc_pas_supprime(service, backend, basic_fit, paris):
    """Si l'événement change (sur l'iPhone) pendant que la fenêtre est ouverte,
    on ne supprime pas : Arthur a validé l'ancienne version, pas la nouvelle."""
    def edit_then_confirm(question):
        backend.add("Perso", basic_fit, make_ics("bf", "Basic Fit (déplacé)", at(paris, 2026, 9, 29, 18), at(paris, 2026, 9, 29, 19)))
        return True
    result = await delete(service, {"calendar": "Perso", "event_id": basic_fit}, native_confirm=edit_then_confirm)
    assert result.is_error and "modifié ailleurs" in result.content[0].text
    assert still_there(backend, basic_fit)
