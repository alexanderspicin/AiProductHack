import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

pytest.importorskip("pipecat")


def test_voice_stop_flushes_transcript_and_releases_session(tmp_path, monkeypatch):
    from backend.app import bot
    from backend.text_app import voice_routes
    from backend.text_app.main import create_app
    from backend.text_app.store import Store
    from backend.text_app.agent import Agent
    from backend.text_app.budget import OpenAIRequestBudget
    from backend.text_app.models import Settings
    store = Store(tmp_path / "workspace.db")
    app = create_app(store=store, agent=Agent(OpenAIRequestBudget(path=tmp_path / "usage.db")))
    store.put("settings", "main", Settings(voice_mode="avatar"))
    monkeypatch.setattr(voice_routes, "pipeline_status", lambda: {"available": True})

    async def run(transport, args, training):
        done = asyncio.Event()
        async def cancel():
            done.set()
        training.worker = SimpleNamespace(cancel=cancel)
        await training.user_message("Я предлагаю пилот.")
        await done.wait()
        await training.assistant_message("Давайте обсудим", interrupted=True)

    monkeypatch.setattr(bot, "run_bot", run)
    with TestClient(app) as client:
        sid = client.post("/api/text/sessions", json={"scenario_id": "sales-objection", "consent": True,
             "voice_consent": True, "request_id": "websocket-session"}).json()["id"]
        url = f"/api/text/sessions/{sid}/voice/ws"
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(url, headers={"origin": "https://unrelated.example"}):
                pass
        with client.websocket_connect(url, headers={"origin": "http://localhost:5174"}):
            assert client.post(f"/api/text/sessions/{sid}/end").status_code == 409
            assert client.post(f"/api/text/sessions/{sid}/voice/stop").status_code == 200
        session = store.session(sid)
        assert session.turns[0].user_text == "Я предлагаю пилот."
        assert session.turns[0].reply == "Давайте обсудим"
        assert session.turns[0].interrupted
        assert sid not in app.state.voice_connections
