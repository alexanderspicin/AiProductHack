"""Scenario adapter. Speech factories and VisemeProcessor are the team's actual code."""
from . import team_source
from app.avatar.viseme_processor import VisemeProcessor
from app.pipeline.stt import make_stt
from app.pipeline.llm import make_llm
from app.pipeline.tts import make_tts
from app.pipeline.transport import transport_params
from app.pipeline.turn_detection import make_user_aggregator_params
from pipecat.frames.frames import LLMUpdateSettingsFrame, TTSSpeakFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.workers.runner import WorkerRunner
from .team_usage import TrainingUsageObserver


async def run_bot(transport, runner_args, training):
    stt, llm, tts = make_stt(), make_llm(), make_tts()
    context = LLMContext(messages=training.history())

    async def advance_stage(params):
        result = await training.advance(params.arguments.get("stage_id"), params.arguments.get("evidence"), params.tool_call_id)
        await params.result_callback(result)

    context.set_tools(ToolsSchema(standard_tools=[FunctionSchema(
        name="advance_stage", description="Отметить цель сценария дословной цитатой участника. Не озвучивать служебный учёт.",
        properties={"stage_id": {"type": "string"}, "evidence": {"type": "string"}},
        required=["stage_id", "evidence"], handler=advance_stage,
    )]))
    user, assistant = LLMContextAggregatorPair(context, user_params=make_user_aggregator_params())

    @user.event_handler("on_user_turn_message_added")
    async def user_message(aggregator, message):
        await training.user_message(message.content)

    @assistant.event_handler("on_assistant_turn_stopped")
    async def assistant_message(aggregator, message):
        await training.assistant_message(message.content, message.interrupted)

    visemes = VisemeProcessor()
    pipeline = Pipeline([transport.input(), stt, user, llm, tts, visemes, transport.output(), assistant])
    usage = TrainingUsageObserver(training, llm)
    worker = PipelineWorker(pipeline, observers=[usage], params=PipelineParams(enable_metrics=True, enable_usage_metrics=True),
                            idle_timeout_secs=runner_args.pipeline_idle_timeout_secs)
    training.worker = worker
    runner = WorkerRunner(handle_sigint=runner_args.handle_sigint)
    await runner.add_workers(worker)

    @worker.rtvi.event_handler("on_client_ready")
    async def ready(rtvi):
        from pipecat.services.openai.llm import OpenAILLMService
        model = training.session.settings.model
        delta = OpenAILLMService.Settings(system_instruction=training.instruction(), model=model,
            max_completion_tokens=600, extra={"reasoning_effort": "none"} if model == "gpt-5.6-luna" else {})
        greeting = training.session.scenario.stages[0].opening_line if not training.session.turns else "Продолжим наш разговор."
        await worker.queue_frames([LLMUpdateSettingsFrame(delta=delta), TTSSpeakFrame(greeting)])

    @worker.rtvi.event_handler("on_client_message")
    async def client_message(rtvi, message):
        if message.type == "interrupt":
            await rtvi.interrupt_bot()
            await worker.flush_pipeline()

    @transport.event_handler("on_client_disconnected")
    async def disconnected(transport, client):
        await runner.cancel()

    try:
        await runner.run()
    finally:
        await visemes._stop_ticker()
        usage.finish_unknown()
