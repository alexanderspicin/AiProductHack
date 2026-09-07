import json

import pytest

from backend.text_app.agent import Agent
from backend.text_app.budget import OpenAIRequestBudget
from backend.text_app.models import FlexibleDecision, GoalObservation, Session, Settings, StartRequest, Turn, TurnRequest
from backend.text_app.progress import record_goals
from backend.text_app.roleplay import role_instruction
from backend.text_app.seeds import builtin_scenarios, seed, with_public_situation
from backend.text_app.service import Service, scenario_view, session_view
from backend.text_app.store import Store
from backend.text_app.voice_training import VoiceTraining


@pytest.fixture
async def service(tmp_path):
    store = Store(tmp_path / "app.sqlite3")
    seed(store)
    return Service(store, Agent(OpenAIRequestBudget(path=tmp_path / "budget.sqlite3")))


async def start(service):
    return await service.start(StartRequest(scenario_id="feedback", request_id="flexible-start", consent=True))


def observation(stage_id, quote="Что помешало закончить вовремя?"):
    return GoalObservation(stage_id=stage_id, quote=quote)


def user_turn(session, text="Что помешало закончить вовремя?", status="committed"):
    session.turns.append(Turn(id=f"t{len(session.turns)}", request_id=f"request-{len(session.turns)}", user_text=text,
                              reply="Чужой ответ", stage_index=session.stage_index, status=status))


async def test_out_of_order_then_fill_gap_persists_and_skips_observed(service):
    s = await start(service)
    assert s.progress_mode == "flexible"
    user_turn(s)
    assert record_goals(s, [observation("cause")]) == ["cause"]
    assert s.stage_index == 0
    user_turn(s, "Отчёт снова задержался, коллеги не смогли закончить сводку.")
    assert record_goals(s, [observation("facts", s.turns[-1].user_text)]) == ["facts"]
    assert s.stage_index == 2
    service.save(s)
    restored = Store(service.store.path).session(s.id)
    assert [g.stage_id for g in restored.stage_progress] == ["cause", "facts"]
    assert restored.stage_progress[0].turn_id == "t0"
    assert session_view(restored)["progress_mode"] == "flexible"


async def test_multiple_goals_are_idempotent_without_automatic_completion(service):
    s = await start(service)
    user_turn(s)
    goals = [observation(stage.id) for stage in s.scenario.stages]
    assert len(record_goals(s, goals)) == 3
    assert record_goals(s, goals) == []
    assert s.status == "active" and s.stage_index == 2


@pytest.mark.parametrize("status", ["pending", "cancelled", "failed"])
async def test_uncommitted_user_text_cannot_confirm_goals(service, status):
    s = await start(service)
    user_turn(s, status=status)
    assert record_goals(s, [observation("cause")]) == []


async def test_unknown_goal_fabricated_quote_and_assistant_text_rejected(service):
    s = await start(service)
    user_turn(s)
    assert record_goals(s, [observation("unknown"), observation("cause", "Чужой ответ"), observation("facts", "Выдуманная цитата")]) == []
    s.status = "completed"
    assert record_goals(s, [observation("cause")]) == []


async def test_finish_requires_all_goals_not_last_stage_pointer(service):
    s = await start(service)
    async def answer(snapshot):
        return FlexibleDecision(reply="Всего доброго.", action="finish", goals=[observation("agreement", snapshot.turns[-1].user_text)])
    service.agent.turn = answer
    result = await service.turn(s.id, TurnRequest(text="Предлагаю созвон завтра в десять.", request_id="one-final-goal"))
    assert result.status == "active" and result.stage_index == 0
    assert len(result.stage_progress) == 1
    async def remaining(snapshot):
        return FlexibleDecision(reply="Договорились.", action="finish", goals=[observation(g, snapshot.turns[-1].user_text) for g in ("facts", "cause")])
    service.agent.turn = remaining
    result = await service.turn(s.id, TurnRequest(text="Другие цели в синтетическом тесте.", request_id="remaining-goals"))
    assert result.status == "completed" and result.completion_reason == "scenario_complete"


async def test_manual_finish_keeps_missing_goals_and_legacy_json_is_ordered(service):
    s = await start(service)
    ended = await service.end(s.id)  # No committed turns, no API request.
    assert ended.status == "completed" and ended.stage_progress == []
    legacy = s.model_dump(exclude={"progress_mode", "stage_progress"})
    restored = Session.model_validate(legacy)
    assert restored.progress_mode == "ordered" and restored.stage_progress == []


async def test_voice_tool_records_future_goal_reconnects_and_rejects_bad_ids(service):
    s = await start(service)
    voice = VoiceTraining(service, s.id)
    await voice.user_message("Что помешало закончить вовремя?")
    result = await voice.advance("cause", "Что помешало закончить вовремя?", "tool1")
    assert not result["advanced"] and result["goals"][1]["observed"]
    reconnected = VoiceTraining(service, s.id)
    assert "уже" in (await reconnected.advance("cause", "Что помешало закончить вовремя?", "tool2"))["error"]
    for bad in [None, "", " " * 10, "x" * 81]:
        assert "error" in await reconnected.advance(bad, "Что помешало закончить вовремя?", "bad")
    assert len(reconnected.session.stage_progress) == 1
    assert '"observed": true' in reconnected.instruction()


async def test_spoken_prompt_shared_not_coach_and_no_hidden_fields_in_public_brief(service):
    s = await start(service)
    system = role_instruction(s)
    assert system in VoiceTraining(service, s.id).instruction()
    captured = []
    async def generate(session, messages, schema, purpose):
        captured.extend(messages)
        assert schema is FlexibleDecision
        return FlexibleDecision(reply="Ответ", action="stay", goals=[])
    service.agent._generate = generate
    await service.agent.turn(s)
    assert system in captured[0]["content"]
    assert "На оскорбление спокойно обозначь личную границу" in system
    assert "Не обучай даже по просьбе" in system
    assert "opening_line" not in captured[0]["content"]
    assert s.scenario.criteria[0].description not in system
    public = scenario_view(s.scenario)
    assert public["situation"] and "context" not in public and "manner" not in public
    assert s.scenario.context not in json.dumps(public, ensure_ascii=False)


def test_builtin_brief_enrichment_never_overwrites_edited_or_custom_scenarios():
    for template in builtin_scenarios():
        old = template.model_copy(deep=True, update={"situation": ""})
        assert with_public_situation(old).situation == template.situation
        assert old.situation == ""
        edited = old.model_copy(update={"context": "Автор изменил исходные обстоятельства."})
        assert with_public_situation(edited).situation == ""
        own = old.model_copy(update={"situation": "Вводная автора"})
        assert with_public_situation(own).situation == "Вводная автора"


async def test_demo_remains_ordered(service):
    service.store.put("settings", "main", Settings(provider="demo"))
    s = await start(service)
    assert s.progress_mode == "ordered"
