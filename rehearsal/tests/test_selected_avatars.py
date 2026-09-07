"""Selected profiles and provider lifecycle. All HTTP is mocked, no credits spent."""
import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.text_app.models import Settings, StartRequest
from backend.text_app.store import Conflict, Store
from backend.text_app.main import create_app
from backend.text_app.agent import Agent
from backend.text_app.budget import OpenAIRequestBudget


@pytest.fixture
def app(tmp_path):
    agent = Agent(OpenAIRequestBudget(path=tmp_path / "usage.db"))
    agent.opening = AsyncMock(return_value="Здравствуйте. Давайте обсудим ситуацию.")
    return create_app(store=Store(tmp_path / "workspace.db"), agent=agent)


async def test_methodist_can_select_both_without_changing_model(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        data = (await client.get('/api/text/bootstrap?role=methodist')).json()
        assert 'presentation' in data and 'settings' not in data
        for profile in ['tavus_sergei', 'anam_tatiana']:
            r = await client.put('/api/text/presentation', json={**data['presentation'], 'avatar_profile': profile, 'voice_mode': 'avatar'})
            assert r.status_code == 200
            data['presentation'] = r.json()
            assert app.state.service.store.settings().avatar_profile == profile
            assert app.state.service.store.settings().model == 'gpt-5.6-luna'
        assert (await client.put('/api/text/presentation', json={**data['presentation'], 'model': 'arbitrary'})).status_code == 422


async def test_profile_is_snapshot_and_old_settings_keep_legacy(app):
    store = app.state.service.store
    assert Settings().avatar_profile == 'legacy_3d'
    store.put('settings', 'main', Settings(avatar_profile='tavus_sergei', voice_mode='avatar'))
    session = await app.state.service.start(StartRequest(scenario_id='sales-objection', participant='Тест',
        request_id='selected-profile-test', consent=True, voice_consent=True))
    store.put('settings', 'main', Settings(avatar_profile='anam_tatiana', voice_mode='avatar'))
    assert store.session(session.id).settings.avatar_profile == 'tavus_sergei'
    assert session.scenario.npc_name == 'Даниил'
    assert store.scenario('sales-objection').npc_name != 'Даниил'
    assert session.scenario.npc_role == store.scenario('sales-objection').npc_role
    from backend.text_app.service import session_view
    assert session_view(store.session(session.id))['avatar_profile'] == 'tavus_sergei'


async def test_tavus_lease_duplicate_stop_and_failure_cleanup(monkeypatch):
    from backend.text_app.avatar_sessions import AvatarSessions
    calls = []
    async def http(request):
        calls.append((request.method, request.url.path))
        if request.url.path == '/v2/pals': return httpx.Response(200, json={'pal_id':'pal-test'})
        if request.url.path == '/v2/conversations':
            return httpx.Response(200, json={'conversation_id':'conversation-test', 'conversation_url':'https://example.daily.co/room'})
        return httpx.Response(200, json={})
    monkeypatch.setenv('TAVUS_API_KEY', 'mock-key')
    async with httpx.AsyncClient(transport=httpx.MockTransport(http)) as client:
        manager = AvatarSessions(client=client)
        first = await manager.prepare('session', 'tavus_sergei', 'request-1')
        second = await manager.prepare('session', 'tavus_sergei', 'request-1')
        assert first == second
        with pytest.raises(Conflict): await manager.prepare('session', 'tavus_sergei', 'request-1', audio_only=True)
        with pytest.raises(Conflict): await manager.prepare('session', 'tavus_sergei', 'request-2')
        assert calls.count(('POST', '/v2/conversations')) == 1
        await manager.stop('session')
        await manager.stop('session')
        assert calls.count(('POST', '/v2/conversations/conversation-test/end')) == 1
        await manager.close()


async def test_cancel_before_prepare_and_stale_stop_do_not_open_or_close_new_call(monkeypatch):
    from backend.text_app.avatar_sessions import AvatarSessions
    monkeypatch.setenv('ANAM_API_KEY', 'test')
    calls = []
    def http(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={'sessionToken':'token'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(http)) as client:
        manager = AvatarSessions(client=client)
        await manager.stop('one', 'old-request')
        with pytest.raises(Conflict): await manager.prepare('one', 'anam_tatiana', 'old-request')
        assert not calls
        new = await manager.prepare('one', 'anam_tatiana', 'new-request')
        await manager.stop('one', 'old-request')
        assert manager.leases['one'].token == new['lease']
        await manager.close()


async def test_anam_token_scoped_and_no_key_in_response(monkeypatch):
    from backend.text_app.avatar_sessions import AvatarSessions
    import json
    seen = []
    async def http(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={'sessionToken':'temporary-session-token'})
    monkeypatch.setenv('ANAM_API_KEY', 'mock-secret-must-stay-server')
    async with httpx.AsyncClient(transport=httpx.MockTransport(http)) as client:
        manager = AvatarSessions(client=client)
        result = await manager.prepare('session', 'anam_tatiana', 'request-1')
        assert 'mock-secret' not in str(result)
        assert seen[0]['personaConfig']['enableAudioPassthrough'] is True
        assert seen[0]['personaConfig']['maxSessionLengthSeconds'] <= 180
        assert seen[0]['sessionOptions']['enableSessionReplay'] is False
        await manager.close()


async def test_no_second_live_session_while_first_is_reserved(monkeypatch):
    from backend.text_app.avatar_sessions import AvatarSessions
    monkeypatch.setenv('ANAM_API_KEY', 'test')
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={'sessionToken':'token'}))) as client:
        manager = AvatarSessions(client=client)
        await manager.prepare('one', 'anam_tatiana', 'first')
        with pytest.raises(Conflict): await manager.prepare('two', 'anam_tatiana', 'second')
        await manager.close()


async def test_lost_websocket_does_not_skip_avatar_cleanup(app, monkeypatch):
    from types import SimpleNamespace
    from starlette.websockets import WebSocketDisconnect
    from backend.app import bot
    from pipecat.transports.websocket import fastapi
    store = app.state.service.store
    store.put('settings', 'main', Settings(avatar_profile='tavus_sergei', voice_mode='avatar'))
    session = await app.state.service.start(StartRequest(scenario_id='sales-objection',
        request_id='cleanup-disconnected-test', consent=True, voice_consent=True))
    manager = app.state.avatar_sessions
    prepared = await manager.prepare(session.id, 'tavus_sergei', 'cleanup-request', audio_only=True)
    # Simulate a allocated video without contacting the provider.
    manager.leases[session.id].conversation_id = 'fake-conversation'
    end = AsyncMock()
    monkeypatch.setattr(manager, '_end_tavus', end)
    monkeypatch.setattr(bot, 'run_bot', AsyncMock())
    monkeypatch.setattr(fastapi, 'FastAPIWebsocketTransport', lambda *_: None)
    ws = SimpleNamespace(headers={'origin':'http://localhost:5176'}, query_params={'lease':prepared['lease']},
                         accept=AsyncMock(), close=AsyncMock(side_effect=WebSocketDisconnect(1006)))
    endpoint = next(r.endpoint for r in app.routes if r.path == '/api/text/sessions/{sid}/voice/ws')
    await endpoint(session.id, ws)
    end.assert_awaited_once()
    assert session.id not in manager.leases
    assert session.id not in app.state.voice_connections
