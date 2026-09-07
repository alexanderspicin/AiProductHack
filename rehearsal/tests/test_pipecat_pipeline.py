"""Real pipeline assembly with only external service factories replaced. No API calls."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("pipecat")


@pytest.mark.parametrize("profile", ["legacy_3d", "tavus_sergei", "anam_tatiana"])
async def test_original_pipeline_order_and_training_context(monkeypatch, tmp_path, profile):
    from backend.app import bot
    from pipecat.processors.frame_processor import FrameProcessor
    from backend.text_app.voice_training import VoiceTraining
    from backend.text_app.models import Settings, StartRequest
    from backend.text_app.agent import Agent
    from backend.text_app.budget import OpenAIRequestBudget
    from backend.text_app.service import Service
    from backend.text_app.store import Store
    from backend.text_app.seeds import seed

    store = Store(tmp_path / "workspace.db"); seed(store)
    store.put("settings", "main", Settings(voice_mode="avatar", avatar_profile=profile))
    service = Service(store, Agent(OpenAIRequestBudget(path=tmp_path / "usage.db")))
    service.agent.opening = AsyncMock(return_value="Я его уже отправила." if profile == "anam_tatiana" else "Я его уже отправил.")
    session = await service.start(StartRequest(scenario_id="sales-objection", request_id="pipeline-assembly", consent=True, voice_consent=True))
    training = VoiceTraining(service, session.id)
    stt, llm, tts = FrameProcessor(), FrameProcessor(), FrameProcessor()
    monkeypatch.setattr(bot, "make_stt", lambda: stt)
    llm_factory = MagicMock(return_value=llm)
    monkeypatch.setattr(bot, "make_llm", llm_factory)
    monkeypatch.setattr(bot, "make_tts", lambda **kwargs: tts)
    monkeypatch.setattr(bot, "make_cartesia", lambda *args: tts)
    transport = MagicMock()
    incoming, outgoing = FrameProcessor(), FrameProcessor()
    transport.input.return_value = incoming; transport.output.return_value = outgoing
    transport.event_handler.side_effect = lambda name: lambda handler: handler
    runner = SimpleNamespace(add_workers=AsyncMock(), run=AsyncMock(), cancel=AsyncMock())
    monkeypatch.setattr(bot, "WorkerRunner", lambda **kwargs: runner)
    original_pipeline = bot.Pipeline
    captured = []
    def pipeline(parts):
        captured.extend(parts)
        return original_pipeline(parts)
    monkeypatch.setattr(bot, "Pipeline", pipeline)
    original_worker = bot.PipelineWorker
    handlers = {}
    def worker(*args, **kwargs):
        instance = original_worker(*args, **kwargs)
        register = instance.rtvi.event_handler
        def event_handler(name):
            def decorate(handler):
                handlers[name] = handler
                return register(name)(handler)
            return decorate
        instance.rtvi.event_handler = event_handler
        instance.queue_frames = AsyncMock()
        return instance
    monkeypatch.setattr(bot, "PipelineWorker", worker)
    await bot.run_bot(transport, SimpleNamespace(handle_sigint=False, pipeline_idle_timeout_secs=300), training)
    assert captured[0] is incoming and captured[1] is stt
    assert captured[3] is llm and captured[4] is tts
    assert type(captured[2]).__name__ == "LLMUserAggregator"
    assert type(captured[5]).__name__ == ("VisemeProcessor" if profile == "legacy_3d" else "RemoteAudioProcessor")
    assert captured[6] is outgoing
    assert type(captured[7]).__name__ == "LLMAssistantAggregator"
    assert session.scenario.context in llm_factory.call_args.kwargs["instruction"]
    assert training.worker is not None
    await handlers["on_client_ready"](training.worker.rtvi)
    from backend.text_app.service import session_view
    from pipecat.frames.frames import TTSSpeakFrame
    frames = training.worker.queue_frames.call_args.args[0]
    assert len(frames) == 1 and isinstance(frames[0], TTSSpeakFrame)
    assert frames[0].text == session_view(session)["opening_message"] == training.history()[0]["content"]
