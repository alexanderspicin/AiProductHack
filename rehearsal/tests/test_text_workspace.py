import asyncio
import json

import httpx
import pytest

from backend.text_app.budget import OpenAIRequestBudget
from backend.text_app.agent import Agent, AgentError, manual_report, validate_report
from backend.text_app.main import create_app
from backend.text_app.models import Assessment, Decision, Evidence, FlexibleDecision, GoalObservation, Grade, ScenarioDraft, Session, Settings, StartRequest, Turn, TurnRequest
from backend.text_app.seeds import seed
from backend.text_app.service import Service
from backend.text_app.store import Conflict, Store


class FakeAgent(Agent):
    def __init__(self, path):
        super().__init__(OpenAIRequestBudget(path=path))
        self.calls = 0
        self.reports = 0
        self.decision = Decision(reply="Расскажите подробнее, что вы предлагаете?", action="advance")
        self.gate = None
        self.entered = asyncio.Event()

    async def turn(self, session):
        self.calls += 1
        self.entered.set()
        if self.gate:
            try:
                await self.gate.wait()
            except asyncio.CancelledError:
                # Non-cooperative provider: the service must still reject a late answer.
                await self.gate.wait()
        return self.decision

    async def assess(self, session):
        self.reports += 1
        return manual_report(session, "Synthetic test, no API calls")


@pytest.fixture
def fixture(tmp_path):
    store = Store(tmp_path / "workspace.sqlite3")
    seed(store)
    agent = FakeAgent(tmp_path / "budget.sqlite3")
    return store, agent, Service(store, agent)


async def start(service):
    return await service.start(StartRequest(scenario_id="sales-objection", consent=True, request_id="start-123456"))


async def test_start_idempotent_and_published_only(fixture):
    store, _, service = fixture
    s = await start(service)
    assert (await start(service)).id == s.id
    scenario = store.scenario("sales-objection")
    scenario.status = "draft"
    store.put("scenario", scenario.id, scenario)
    with pytest.raises(Conflict, match="не опубликован"):
        await service.start(StartRequest(scenario_id=scenario.id, consent=True, request_id="different-123"))
    assert store.session(s.id).scenario.status == "published"


async def test_explicit_consent_and_snapshot(fixture):
    store, _, service = fixture
    with pytest.raises(Conflict, match="Подтвердите"):
        await service.start(StartRequest(scenario_id="sales-objection", request_id="consent-test"))
    s = await start(service)
    scenario = store.scenario(s.scenario.id)
    scenario.title = "Новое название"
    store.put("scenario", scenario.id, scenario)
    settings = Settings(mode="assessment", provider="demo")
    store.put("settings", "main", settings)
    restored = store.session(s.id)
    assert restored.scenario.title != scenario.title
    assert restored.settings.mode == "practice"


async def test_duplicate_turns_and_early_finish_guard(fixture):
    store, agent, service = fixture
    s = await start(service)
    agent.decision = Decision(reply="Прощайте", action="finish")
    request = TurnRequest(text="Добрый день!", request_id="turn-12345678")
    result = await service.turn(s.id, request)
    assert result.status == "active" and result.turns[0].action == "stay"
    again = await service.turn(s.id, request)
    assert len(again.turns) == 1 and agent.calls == 1
    with pytest.raises(Conflict):
        await service.turn(s.id, request.model_copy(update={"text": "Подмена"}))


async def test_cancelled_generation_never_returns(fixture):
    store, agent, service = fixture
    s = await start(service)
    goal_id = s.scenario.stages[0].id
    agent.decision = FlexibleDecision(reply="Ответ", action="stay", goals=[GoalObservation(stage_id=goal_id, quote="Первый ответ")])
    agent.gate = asyncio.Event()
    task = asyncio.create_task(service.turn(s.id, TurnRequest(text="Первый ответ", request_id="turn-cancelled")))
    await agent.entered.wait()
    stopped = await service.cancel(s.id, "turn-cancelled")
    assert stopped.turns[0].status == "cancelled"
    agent.gate.set()
    result = await task
    assert result.turns[0].reply == "" and result.stage_index == 0
    assert result.stage_progress == []
    agent.gate = None
    agent.decision = FlexibleDecision(reply="Новый ответ", action="stay", goals=[GoalObservation(stage_id=goal_id, quote="Новый ответ")])
    second = await service.turn(s.id, TurnRequest(text="Новый ответ", request_id="turn-second"))
    assert second.stage_index == 1 and second.turns[-1].status == "committed"
    await service.cancel(s.id, "turn-cancelled")
    assert store.session(s.id).turns[-1].status == "committed"


async def test_cancel_before_request_is_registered(fixture):
    _, agent, service = fixture
    s = await start(service)
    await service.cancel(s.id, "turn-tombstone")
    result = await service.turn(s.id, TurnRequest(text="Поздний пакет", request_id="turn-tombstone"))
    assert agent.calls == 0 and result.turns == []


async def test_concurrent_turn_is_rejected_and_end_is_idempotent(fixture):
    _, agent, service = fixture
    s = await start(service)
    agent.gate = asyncio.Event()
    task = asyncio.create_task(service.turn(s.id, TurnRequest(text="Текст", request_id="turn-pending")))
    await agent.entered.wait()
    with pytest.raises(Conflict, match="ещё готовится"):
        await service.turn(s.id, TurnRequest(text="Другой текст", request_id="turn-conflict"))
    result = await service.end(s.id)
    agent.gate.set()
    await task
    assert result.status == "completed" and result.report_status == "ready"
    await service.end(s.id)
    assert agent.reports == 1


async def test_turn_limit_and_no_more_generation(fixture):
    store, agent, service = fixture
    store.put("settings", "main", Settings(max_turns=3))
    s = await start(service)
    agent.decision = Decision(reply="Продолжим", action="stay")
    for index in range(3):
        result = await service.turn(s.id, TurnRequest(text="Реплика", request_id=f"turn-number-{index}"))
    assert result.status == "completed" and result.completion_reason == "turn_limit"
    with pytest.raises(Conflict, match="завершена"):
        await service.turn(s.id, TurnRequest(text="Реплика", request_id="turn-too-many"))


async def test_persistence_and_recovery(fixture):
    store, agent, service = fixture
    s = await start(service)
    s.turns.append(Turn(id="t", request_id="interrupted", user_text="Сохранить", stage_index=0))
    s.report_status = "pending"
    store.put("session", s.id, s)
    restarted = Store(store.path)
    Service(restarted, agent)
    restored = restarted.session(s.id)
    assert restored.turns[0].status == "cancelled"
    assert restored.turns[0].user_text == "Сохранить"
    assert restored.report_status == "failed"


async def test_score_requires_exact_user_quote(fixture):
    _, _, service = fixture
    s = await start(service)
    s.turns.append(Turn(id="t1", request_id="valid-turn", user_text="Что именно не устроило?", reply="Ответ персонажа", stage_index=0, status="committed"))
    assessment = Assessment(summary="Предварительный разбор", strengths=[], next_steps=[], criteria=[
        Grade(criterion_id="listening", score=4, comment="Есть вопрос", evidence=[Evidence(turn_id="t1", quote="Что именно не устроило?")], recommendation="Уточнить причины"),
        Grade(criterion_id="discovery", score=5, comment="Не должно попасть", evidence=[Evidence(turn_id="t1", quote="Ответ персонажа")], recommendation="Проверить"),
    ])
    report = validate_report(s, assessment)
    assert report.covered == 1 and report.total == 5 and report.overall_score == 80
    assert report.criteria[1].score is None and report.criteria[1].evidence == []
    assert "Неподтверждённые" in report.warning
    assert len(report.criteria) == 5


async def test_no_observations_is_not_zero(fixture):
    _, _, service = fixture
    s = await start(service)
    r = validate_report(s, Assessment(summary="Нет данных", criteria=[], strengths=[], next_steps=[]))
    assert r.overall_score is None and r.covered == 0


async def test_real_adapter_schema_budget_and_no_retry(tmp_path, fixture):
    _, _, service = fixture
    s = await start(service)
    s.turns.append(Turn(id="t", request_id="mock-request", user_text="Что вас беспокоит?", stage_index=0))
    requests = []
    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        assert body["model"] == "gpt-5.6-luna" and body["reasoning_effort"] == "none"
        assert body["response_format"]["json_schema"]["strict"] is True
        assert body["messages"][-1]["content"] == "Что вас беспокоит?"
        assert "temperature" not in body
        assert body["response_format"]["json_schema"]["name"] == "flexibledecision"
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": '{"reply":"Я сомневаюсь в результате.","action":"stay","goals":[]}'}}]})
    budget = OpenAIRequestBudget("synthetic-key", enabled=True, max_requests=2, path=tmp_path / "isolated.sqlite3")
    agent = Agent(budget, httpx.MockTransport(respond))
    assert (await agent.turn(s)).action == "stay"
    # Compatibility cap is ignored: the user removed the local text limit.
    for _ in range(4):
        assert (await agent.turn(s)).action == "stay"
    assert len(requests) == budget.used_requests() == 5


@pytest.mark.parametrize("status", [401, 429, 500])
async def test_provider_errors_do_not_leak_body_or_retry(tmp_path, fixture, status):
    _, _, service = fixture
    s = await start(service)
    budget = OpenAIRequestBudget("synthetic-key", enabled=True, max_requests=5, path=tmp_path / "error.sqlite3")
    agent = Agent(budget, httpx.MockTransport(lambda request: httpx.Response(status, json={"error": "SECRET_RESPONSE"})))
    with pytest.raises(AgentError) as exc:
        await agent.turn(s)
    assert "SECRET" not in str(exc.value)
    assert budget.used_requests() == 1


async def test_bootstrap_privacy_origin_revision_and_review(fixture):
    store, agent, _ = fixture
    app = create_app(store=store, agent=agent)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        public = (await client.get('/api/text/bootstrap')).json()
        assert 'settings' not in public and 'budget' not in public
        assert all('context' not in s and 'manner' not in s for s in public['scenarios'])
        admin = (await client.get('/api/text/bootstrap?role=admin')).json()
        assert 'api_key' not in json.dumps(admin) and 'settings' in admin
        settings = admin['settings']
        assert (await client.put('/api/text/settings', json=settings)).status_code == 200
        assert (await client.put('/api/text/settings', json=settings)).status_code == 409
        assert (await client.put('/api/text/settings', json=settings, headers={'Origin': 'https://untrusted.example'})).status_code == 403
        raw = store.scenario('sales-objection').model_dump(exclude={'id', 'updated_at'})
        assert (await client.put('/api/text/scenarios/sales-objection', json=raw)).status_code == 200
        assert (await client.put('/api/text/scenarios/sales-objection', json=raw)).status_code == 409
        s = (await client.post('/api/text/sessions', json={'scenario_id': 'sales-objection', 'consent': True, 'request_id': 'api-session-test'})).json()
        assert 'context' not in s['scenario'] and 'settings' not in s
        await client.post(f"/api/text/sessions/{s['id']}/end")
        reviewed = await client.put(f"/api/text/sessions/{s['id']}/review", json={'note': 'Проверено по стенограмме', 'reviewed': True})
        assert reviewed.status_code == 200
        assert store.session(s['id']).reviewed is True


def test_scenario_whitespace_and_duplicate_validation(fixture):
    store, _, _ = fixture
    raw = store.scenario('sales-objection').model_dump(exclude={'id', 'updated_at', 'revision'})
    raw['title'] = '   '
    with pytest.raises(ValueError):
        ScenarioDraft.model_validate(raw)
    raw['title'] = 'Пример'
    raw['stages'][1]['id'] = raw['stages'][0]['id']
    with pytest.raises(ValueError, match='уникальными'):
        ScenarioDraft.model_validate(raw)


async def test_failed_report_requires_explicit_retry(fixture):
    store, agent, service = fixture
    s = await start(service)
    async def fail(session):
        agent.reports += 1
        raise AgentError("Синтетический сбой")
    agent.assess = fail
    first = await service.end(s.id)
    assert first.report_status == 'failed' and first.report is None
    await service.end(s.id)
    assert agent.reports == 1
    await service.end(s.id, retry=True)
    assert agent.reports == 2


async def test_partial_draft_roundtrip_publication_and_snapshot(fixture):
    store, agent, _ = fixture
    app = create_app(store=store, agent=agent)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        draft = {"title": "Заготовка методиста", "stages": [{"id": "first"}], "criteria": [{"id": "quality"}]}
        created = await client.post('/api/text/scenarios', json=draft)
        assert created.status_code == 200
        s = created.json()
        sid = s['id']
        assert s['description'] == '' and s['stages'][0]['opening_line'] == ''
        assert Store(store.path).scenario(sid).title == draft['title']
        assert sid not in [s['id'] for s in (await client.get('/api/text/bootstrap')).json()['scenarios']]
        assert sid in [s['id'] for s in (await client.get('/api/text/bootstrap?role=methodist')).json()['scenarios']]
        start_request = {'scenario_id': sid, 'consent': True, 'request_id': 'partial-draft-start'}
        assert (await client.post('/api/text/sessions', json=start_request)).status_code == 409
        update = {k: v for k, v in s.items() if k not in ('id', 'updated_at')}
        update['status'] = 'published'
        rejected = await client.put(f'/api/text/scenarios/{sid}', json=update)
        assert rejected.status_code == 422
        assert 'Перед публикацией' in rejected.text
        assert store.scenario(sid).status == 'draft' and store.scenario(sid).revision == 1
        complete = store.scenario('sales-objection').model_dump(exclude={'id', 'updated_at', 'revision'})
        complete['title'] = draft['title']
        complete['revision'] = 1
        assert (await client.put(f'/api/text/scenarios/{sid}', json=complete)).status_code == 200
        started = (await client.post('/api/text/sessions', json=start_request)).json()
        assert started['scenario']['revision'] == 2
        unpublish = {**draft, 'revision': 2, 'status': 'draft'}
        assert (await client.put(f'/api/text/scenarios/{sid}', json=unpublish)).status_code == 200
        assert store.session(started['id']).scenario.status == 'published'
        assert store.session(started['id']).scenario.description == complete['description']
        assert (await client.put(f'/api/text/scenarios/{sid}', json=unpublish)).status_code == 409
        assert agent.calls == agent.reports == 0


@pytest.mark.parametrize('field', ['category', 'description', 'employee_role', 'npc_name', 'npc_role', 'manner', 'context'])
def test_partial_fields_allowed_only_until_publication(fixture, field):
    store, _, _ = fixture
    raw = store.scenario('sales-objection').model_dump(exclude={'id', 'updated_at', 'revision'})
    raw[field] = '   '
    with pytest.raises(ValueError, match='Перед публикацией'):
        ScenarioDraft.model_validate(raw)
    for status in ('draft', 'archived'):
        assert getattr(ScenarioDraft.model_validate({**raw, 'status': status}), field) == ''


@pytest.mark.parametrize('group,field', [('stages', 'title'), ('stages', 'objective'), ('stages', 'opening_line'), ('criteria', 'title'), ('criteria', 'description')])
def test_partial_nested_fields_and_limits(fixture, group, field):
    store, _, _ = fixture
    raw = store.scenario('sales-objection').model_dump(exclude={'id', 'updated_at', 'revision'})
    raw[group][0][field] = ''
    with pytest.raises(ValueError, match='Перед публикацией'):
        ScenarioDraft.model_validate(raw)
    raw['status'] = 'draft'
    ScenarioDraft.model_validate(raw)
    raw[group][0][field] = 'x' * 1100
    with pytest.raises(ValueError):
        ScenarioDraft.model_validate(raw)
