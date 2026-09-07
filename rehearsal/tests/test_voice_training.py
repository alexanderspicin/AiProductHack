import httpx
import pytest

from backend.text_app.agent import Agent
from backend.text_app.budget import OpenAIRequestBudget
from backend.text_app.main import create_app
from backend.text_app.models import Settings, StartRequest
from backend.text_app.seeds import seed
from backend.text_app.service import Service
from backend.text_app.store import Store
from backend.text_app.voice_training import VoiceTraining, validate_voice_session


@pytest.fixture
async def training(tmp_path):
    store = Store(tmp_path / "training.sqlite3")
    seed(store)
    store.put("settings", "main", Settings(voice_mode="avatar"))
    service = Service(store, Agent(OpenAIRequestBudget(path=tmp_path / "usage.sqlite3")))
    session = await service.start(StartRequest(scenario_id="sales-objection", request_id="voice-test-session",
                                               consent=True, voice_consent=True))
    return VoiceTraining(service, session.id)


async def test_interrupted_answer_keeps_user_evidence(training):
    await training.user_message("Что вас беспокоит в обучении?")
    await training.assistant_message("Меня беспокоит", interrupted=True)
    s = training.session
    assert len(s.turns) == 1
    assert s.turns[0].status == "committed"
    assert s.turns[0].interrupted
    assert s.turns[0].user_text == "Что вас беспокоит в обучении?"
    assert training.history()[-1]["content"] == "Меня беспокоит"


async def test_stage_requires_real_evidence_and_deduplicates(training):
    stage = training.session.scenario.stages[0].id
    await training.user_message("Давайте выясним причину.")
    assert "error" in await training.advance(stage, "Выдуманная цитата", "call1")
    assert training.session.stage_index == 0
    assert (await training.advance(stage, "выясним причину", "call2"))["advanced"]
    assert not (await training.advance(stage, "выясним причину", "call2"))["advanced"]
    assert training.session.stage_index == 1


async def test_agent_receives_stage_goals_not_canned_opening_lines(training):
    assert 'opening_line' not in training.instruction()
    await training.user_message('Давайте выясним причину.')
    result = await training.advance(training.session.scenario.stages[0].id, 'выясним причину', 'real-citation')
    assert 'opening_line' not in result['stage']


async def test_report_reads_voice_transcript(training):
    await training.user_message("Предлагаю пилот на одной команде.")
    await training.assistant_message("Обсудим условия пилота.")
    observed = []
    async def assess(session):
        from backend.text_app.agent import manual_report
        observed.extend(session.turns)
        return manual_report(session, "fixture")
    training.service.agent.assess = assess
    result = await training.service.end(training.sid)
    assert result.report_status == "ready"
    assert observed[0].user_text == "Предлагаю пилот на одной команде."


async def test_prepare_blocks_without_key_and_text_race(training, monkeypatch):
    monkeypatch.setenv("INWORLD_API_ENABLED", "0")
    app = create_app(store=training.service.store, agent=training.service.agent)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(f"/api/text/sessions/{training.sid}/voice/prepare")
        assert response.status_code == 409
        app.state.voice_connections[training.sid] = (None, training)
        response = await client.post(f"/api/text/sessions/{training.sid}/turns", json={"text":"Тест", "request_id":"voice-race-test"})
        assert response.status_code == 409
        assert (await client.post(f"/api/text/sessions/{training.sid}/end")).status_code == 409


async def test_scenario_is_snapshot_and_no_browser_prompt(training):
    validate_voice_session(training.session)
    assert training.session.scenario.context in training.instruction()
    changed = training.service.store.scenario(training.session.scenario.id)
    changed.context = "Новый сценарий"
    training.service.store.put("scenario", changed.id, changed)
    assert "Новый сценарий" not in training.instruction()
