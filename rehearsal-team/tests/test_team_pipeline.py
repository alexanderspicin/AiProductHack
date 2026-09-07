"""Real module provenance and pipeline assembly. External generators are mocked."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import inspect
import pytest
from pydantic import ValidationError
from backend.text_app.models import Settings, PresentationSettings


def test_remote_profiles_cannot_be_enabled():
    for profile in ("tavus_sergei", "anam_tatiana"):
        with pytest.raises(ValidationError):
            Settings(avatar_profile=profile)
        with pytest.raises(ValidationError):
            PresentationSettings(revision=1, avatar_profile=profile)


def test_imports_are_original_teammate_modules():
    from backend.text_app import team_pipeline as bot
    from backend.text_app.team_source import UPSTREAM
    for obj in (bot.make_stt, bot.make_tts, bot.make_llm, bot.make_user_aggregator_params, bot.VisemeProcessor):
        assert Path(inspect.getfile(obj)).resolve().is_relative_to(UPSTREAM.resolve())
    from app.pipeline.turn_detection import make_user_aggregator_params
    assert bot.make_user_aggregator_params is make_user_aggregator_params


async def test_pipeline_context_greeting_and_manual_interruption(monkeypatch, tmp_path):
    from backend.text_app import team_pipeline as bot
    from pipecat.processors.frame_processor import FrameProcessor
    from backend.text_app.voice_training import VoiceTraining
    from backend.text_app.models import StartRequest
    from backend.text_app.agent import Agent
    from backend.text_app.budget import OpenAIRequestBudget
    from backend.text_app.service import Service
    from backend.text_app.store import Store
    from backend.text_app.seeds import seed
    store = Store(tmp_path / "db"); seed(store)
    store.put("settings", "main", Settings(voice_mode="avatar"))
    service = Service(store, Agent(OpenAIRequestBudget(path=tmp_path / "usage")))
    session = await service.start(StartRequest(scenario_id="sales-objection", request_id="assembly-team", consent=True, voice_consent=True))
    training = VoiceTraining(service, session.id)
    stt, llm, tts = FrameProcessor(), FrameProcessor(), FrameProcessor()
    monkeypatch.setattr(bot, "make_stt", lambda: stt)
    monkeypatch.setattr(bot, "make_llm", lambda: llm)
    monkeypatch.setattr(bot, "make_tts", lambda: tts)
    transport = MagicMock()
    transport.input.return_value = FrameProcessor(); transport.output.return_value = FrameProcessor()
    transport.event_handler.side_effect = lambda name: lambda fn: fn
    runner = SimpleNamespace(add_workers=AsyncMock(), run=AsyncMock(), cancel=AsyncMock())
    monkeypatch.setattr(bot, "WorkerRunner", lambda **kwargs: runner)
    original = bot.Pipeline; parts = []
    def pipeline(items):
        parts.extend(items); return original(items)
    monkeypatch.setattr(bot, "Pipeline", pipeline)
    worker_class = bot.PipelineWorker; handlers = {}
    def worker(*args, **kwargs):
        instance = worker_class(*args, **kwargs)
        instance.rtvi.event_handler = lambda name: lambda fn: handlers.setdefault(name, fn)
        instance.queue_frames = AsyncMock(); instance.flush_pipeline = AsyncMock()
        return instance
    monkeypatch.setattr(bot, "PipelineWorker", worker)
    await bot.run_bot(transport, SimpleNamespace(handle_sigint=False, pipeline_idle_timeout_secs=300), training)
    assert len(parts) == 8 and parts[1] is stt and parts[3] is llm and parts[4] is tts
    assert type(parts[2]).__name__ == "LLMUserAggregator"
    assert type(parts[5]).__module__ == "app.avatar.viseme_processor"
    assert type(parts[-1]).__name__ == "LLMAssistantAggregator"
    await handlers["on_client_ready"](None)
    update, greeting = training.worker.queue_frames.call_args.args[0]
    assert session.scenario.context in update.delta.system_instruction
    assert update.delta.model == session.settings.model
    assert update.delta.extra == {"reasoning_effort": "none"}
    assert greeting.text == training.history()[0]["content"]
    rtvi = SimpleNamespace(interrupt_bot=AsyncMock())
    await handlers["on_client_message"](rtvi, SimpleNamespace(type="interrupt"))
    rtvi.interrupt_bot.assert_awaited_once()
    training.worker.flush_pipeline.assert_awaited_once()
