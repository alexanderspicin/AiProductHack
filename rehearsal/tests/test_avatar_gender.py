"""No real API calls. Language quality is evaluated separately in run 11."""
import asyncio
import json

import httpx
import pytest

from backend.text_app.agent import Agent, AgentError
from backend.text_app.budget import OpenAIRequestBudget
from backend.text_app.models import Session, Settings, StartRequest
from backend.text_app.seeds import seed
from backend.text_app.service import Service, session_view
from backend.text_app.store import Conflict, Store
from backend.text_app.voice_training import VoiceTraining


def response(text="Я его уже отправила."):
    return httpx.Response(200, json={
        "model": "gpt-5.6-luna", "usage": {"prompt_tokens": 150, "completion_tokens": 20, "total_tokens": 170},
        "choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"opening_line": text})}}],
    })


def workspace(tmp_path, http=None, **settings):
    store = Store(tmp_path / "workspace.db")
    seed(store)
    store.put("settings", "main", Settings(voice_mode="avatar", avatar_profile="anam_tatiana", **settings))
    seen = []
    def handle(request):
        seen.append(json.loads(request.content))
        return http(request) if http else response()
    budget = OpenAIRequestBudget("fixture-key", enabled=True, path=tmp_path / "usage.db")
    agent = Agent(budget, transport=httpx.MockTransport(handle))
    return Service(store, agent), seen


def start(request_id="gender-test-start", **kwargs):
    return StartRequest(scenario_id="feedback", request_id=request_id, consent=True, voice_consent=True, **kwargs)


@pytest.mark.parametrize("profile,text,gender", [
    ("anam_tatiana", "Я купила, выбрала, решила и подписала. Я готова.", "женском"),
    ("tavus_sergei", "Я купил, выбрал, решил и подписал. Я готов.", "мужском"),
])
async def test_snapshot_shared_by_ui_text_and_voice(tmp_path, profile, text, gender):
    service, seen = workspace(tmp_path, lambda r: response(text))
    service.store.put("settings", "main", Settings(voice_mode="avatar", avatar_profile=profile))
    original = service.store.scenario("feedback").model_dump()
    session = await service.start(start())
    restored = service.store.session(session.id)
    training = VoiceTraining(service, session.id)
    assert session_view(restored)["opening_message"] == text
    assert training.history()[0]["content"] == text
    assert restored.scenario.stages[0].opening_line == text
    assert service.store.scenario("feedback").model_dump() == original
    assert restored.scenario.context == original["context"]
    assert f"в {gender} роде" in seen[0]["messages"][0]["content"]
    assert "прямую речь" in training.instruction()
    captured = []
    async def generate(session, messages, schema, purpose):
        captured.extend(messages)
    service.agent._generate = generate
    await service.agent.turn(restored)
    assert captured[1]["content"] == text
    # Changing the global profile or restarting the service must not alter a saved session.
    service.store.put("settings", "main", Settings(voice_mode="avatar", avatar_profile="legacy_3d"))
    service = Service(service.store, service.agent)
    assert session_view(service.store.session(session.id))["opening_message"] == text
    assert service.store.session(session.id).settings.avatar_profile == profile


async def test_successful_start_and_cache_are_idempotent_and_accounted(tmp_path):
    service, seen = workspace(tmp_path)
    a, b = await asyncio.gather(service.start(start()), service.start(start()))
    assert a.id == b.id
    c = await service.start(start("another-gender-start"))
    assert c.id != a.id
    assert c.scenario.stages[0].opening_line == a.scenario.stages[0].opening_line
    assert len(seen) == 1
    usage = service.agent.budget.status()
    assert service.agent.budget.used_requests() == usage["used_requests"] == 1
    assert usage["usage"]["total_tokens"] == 170
    assert usage["usage"]["estimated_cost_usd"] is not None
    assert usage["usage"]["recent"][0]["operation"] == "text_opening"
    assert seen[0]["max_completion_tokens"] == 650
    with pytest.raises(Conflict):
        await service.start(start(participant="Другой участник"))
    assert len(seen) == 1


async def test_cache_changes_with_profile_source_name_text_and_model(tmp_path):
    service, seen = workspace(tmp_path)
    await service.start(start())
    service.store.put("settings", "main", Settings(voice_mode="avatar", avatar_profile="tavus_sergei"))
    await service.start(start("different-profile"))
    scenario = service.store.scenario("feedback")
    scenario.npc_name = "Алексей"
    service.store.put("scenario", scenario.id, scenario)
    await service.start(start("different-source-name"))
    scenario.stages[0].opening_line = "Я его уже отправил вчера."
    service.store.put("scenario", scenario.id, scenario)
    await service.start(start("different-source-text"))
    service.store.put("settings", "main", Settings(voice_mode="avatar", avatar_profile="tavus_sergei", model="gpt-4.1-mini-2025-04-14"))
    await service.start(start("different-model"))
    assert len(seen) == 5


@pytest.mark.parametrize("bad", [httpx.Response(429), response(""), response(" "), response("x" * 1001), httpx.Response(200, json={})])
async def test_failure_is_not_saved_or_cached_and_has_no_automatic_retry(tmp_path, bad):
    service, seen = workspace(tmp_path, lambda r: bad)
    with pytest.raises(AgentError, match="Тренировка не начата"):
        await service.start(start())
    assert service.store.find_start(start().request_id) is None
    assert service.store.all("session") == []
    assert len(seen) == 1
    assert service.agent._openings == {}
    assert service.agent.budget.status()["usage"]["recent"][0]["state"] == "failed"
    service.agent.transport = httpx.MockTransport(lambda r: response())
    assert (await service.start(start())).scenario.stages[0].opening_line == "Я его уже отправила."


async def test_no_key_or_consent_does_not_start(tmp_path):
    service, seen = workspace(tmp_path)
    with pytest.raises(Conflict):
        await service.start(start().model_copy(update={"consent": False}))
    with pytest.raises(Conflict):
        await service.start(start().model_copy(update={"voice_consent": False}))
    service.agent.budget.api_key = ""
    with pytest.raises(AgentError, match="Тренировка не начата"):
        await service.start(start())
    assert not seen and not service.store.all("session")


async def test_cancellation_leaves_no_partial_start(tmp_path):
    service, seen = workspace(tmp_path)
    entered = asyncio.Event()
    async def http(request):
        entered.set()
        await asyncio.Event().wait()
    service.agent.transport = httpx.MockTransport(http)
    task = asyncio.create_task(service.start(start()))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not service.store.all("session")
    assert not service.agent._openings
    assert service.agent.budget.status()["usage"]["recent"][0]["state"] == "cancelled"


async def test_existing_incorrect_history_is_not_rewritten(tmp_path):
    service, seen = workspace(tmp_path)
    old = Session(id="old-session", participant="Участник", scenario=service.store.scenario("feedback"),
                  settings=service.store.settings(), consent=True, voice_consent=True)
    service.store.save_start(start().request_id, old)
    original = old.scenario.stages[0].opening_line
    assert "отправил" in original
    assert session_view(await service.start(start()))["opening_message"] == original
    assert not seen


@pytest.mark.parametrize("mode,profile", [("text", "anam_tatiana"), ("avatar", "legacy_3d")])
async def test_legacy_and_text_do_not_need_new_request(tmp_path, mode, profile):
    service, seen = workspace(tmp_path)
    service.store.put("settings", "main", Settings(voice_mode=mode, avatar_profile=profile))
    session = await service.start(start())
    assert session.scenario.stages[0].opening_line == service.store.scenario("feedback").stages[0].opening_line
    assert not seen


async def test_selected_demo_is_neutral_and_offline(tmp_path):
    service, seen = workspace(tmp_path, provider="demo")
    service.agent.budget.api_key = ""
    session = await service.start(start())
    assert session.scenario.stages[0].opening_line == "Здравствуйте. Давайте обсудим ситуацию."
    assert (await service.agent.turn(session)).reply == "Спасибо за ответ. Продолжим обсуждение."
    assert not seen
