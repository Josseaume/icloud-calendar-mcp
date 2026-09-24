"""Tests de bout en bout : un vrai client MCP parle au serveur, en mémoire."""

import json

import pytest
from mcp import Client

from conftest import at, make_ics
from icloud_calendar_mcp.server import build_server

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_outils_exposes(service):
    async with Client(build_server(service)) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert {"list_calendars", "list_events"} <= set(tools)
    assert tools["list_events"].annotations.read_only_hint is True
    assert set(tools["list_events"].input_schema["properties"]) == {"start", "end", "calendar"}


async def test_appel_list_events(service, backend, paris):
    backend.add("Perso", "b.ics", make_ics("b", "Basic Fit", at(paris, 2026, 9, 28, 18), at(paris, 2026, 9, 28, 19, 30)))
    async with Client(build_server(service)) as client:
        result = await client.call_tool("list_events", {"start": "2026-09-28", "end": "2026-09-28"})
    assert not result.is_error
    data = json.loads(result.content[0].text)  # ce que Claude lit
    assert data["period"] == "lundi 28 septembre 2026"
    assert data["events"][0]["when"] == "lundi 28 septembre 2026, 18:00 – 19:30"


async def test_erreur_lisible_pour_claude(service):
    async with Client(build_server(service)) as client:
        result = await client.call_tool("list_events", {"start": "lundi", "end": "mardi"})
    assert result.is_error
    assert "Date illisible" in result.content[0].text


async def test_annotations_des_outils_d_ecriture(service):
    async with Client(build_server(service)) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert tools["create_event"].annotations.destructive_hint is False
    assert tools["update_event"].annotations.destructive_hint is True
    assert "calendar" in tools["create_event"].input_schema["required"]


async def test_creation_via_mcp_et_refus_esiee(service, backend):
    async with Client(build_server(service)) as client:
        ok = await client.call_tool("create_event", {
            "calendar": "Perso", "title": "Basic Fit",
            "start": "2026-09-28T18:00", "end": "2026-09-28T19:30"})
        refused = await client.call_tool("create_event", {
            "calendar": "Cours ESIEE", "title": "x",
            "start": "2026-09-28T18:00", "end": "2026-09-28T19:30"})
    assert not ok.is_error
    assert json.loads(ok.content[0].text)["created"]["when"] == "lundi 28 septembre 2026, 18:00 – 19:30"
    assert refused.is_error and "protégé" in refused.content[0].text
    assert [w[0] for w in backend.writes] == ["create"]
