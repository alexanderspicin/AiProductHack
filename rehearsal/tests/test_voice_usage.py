from types import SimpleNamespace
import pytest

pytest.importorskip("pipecat")


async def test_pipecat_metrics_are_counted_once_and_cancel_is_unknown(tmp_path):
    from backend.app.training_usage import TrainingUsageObserver
    from backend.text_app.budget import OpenAIRequestBudget
    from pipecat.frames.frames import LLMFullResponseStartFrame, LLMFullResponseEndFrame, MetricsFrame
    from pipecat.metrics.metrics import LLMUsageMetricsData, LLMTokenUsage
    budget = OpenAIRequestBudget("fake", enabled=True, path=tmp_path / "usage.db")
    llm = object()
    training = SimpleNamespace(service=SimpleNamespace(agent=SimpleNamespace(budget=budget)),
                               session=SimpleNamespace(settings=SimpleNamespace(model="gpt-5.6-luna")))
    observer = TrainingUsageObserver(training, llm)
    async def send(frame):
        await observer.on_push_frame(SimpleNamespace(source=llm, frame=frame))
    await send(LLMFullResponseStartFrame())
    metric = MetricsFrame(data=[LLMUsageMetricsData(processor="fixture", value=LLMTokenUsage(
        prompt_tokens=100, completion_tokens=20, total_tokens=120, cache_read_input_tokens=40))])
    await send(metric)
    await send(metric)
    await send(LLMFullResponseEndFrame())
    await send(LLMFullResponseStartFrame())
    observer.finish_unknown()
    usage = budget.status()["usage"]
    assert usage["total_tokens"] == 120
    assert usage["cached_tokens"] == 40
    assert usage["measured_requests"] == 1
    assert usage["unmeasured_requests"] == 1


async def test_typed_pipecat_message_is_persisted_once():
    from unittest.mock import AsyncMock
    from backend.app.training_usage import TrainingUsageObserver
    from pipecat.frames.frames import LLMMessagesAppendFrame
    training = SimpleNamespace(service=SimpleNamespace(agent=SimpleNamespace(budget=None)),
                               session=SimpleNamespace(settings=SimpleNamespace(model="gpt-5.6-luna")),
                               user_message=AsyncMock())
    observer = TrainingUsageObserver(training, object())
    frame = LLMMessagesAppendFrame(messages=[{"role": "user", "content": "Подождите, уточню."}], run_llm=True)
    await observer.on_push_frame(SimpleNamespace(source=object(), frame=frame))
    await observer.on_push_frame(SimpleNamespace(source=object(), frame=frame))
    training.user_message.assert_awaited_once_with("Подождите, уточню.")
