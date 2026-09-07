from dotenv import load_dotenv
from loguru import logger
from pipecat.frames.frames import LLMRunFrame, TTSSpeakFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.transports.base_transport import BaseTransport
from pipecat.workers.runner import WorkerRunner

from backend.app.avatar.viseme_processor import VisemeProcessor
from backend.app.pipeline.llm import make_llm
from backend.app.pipeline.stt import make_stt
from backend.app.pipeline.transport import transport_params
from backend.app.pipeline.tts import make_tts, make_cartesia
from backend.app.pipeline.turn_detection import make_user_aggregator_params

load_dotenv(override=True)


async def run_bot(transport: BaseTransport, runner_args: RunnerArguments, training=None):
    logger.info("Starting bot")

    stt = make_stt()
    llm = make_llm(instruction=training.instruction(), model=training.session.settings.model,
                   api_key=training.service.agent.budget.api_key,
                   base_url=training.service.agent.budget.base_url) if training else make_llm()
    remote = bool(training and training.session.settings.avatar_profile != "legacy_3d")
    if remote:
        tts = make_cartesia(training.session.settings.avatar_profile)
    elif training:
        from backend.text_app.budget import local_setting
        tts = make_tts(api_key=local_setting("INWORLD_API_KEY"))
    else:
        tts = make_tts()
    if remote:
        from backend.app.avatar.remote_audio import RemoteAudioProcessor
        viseme_processor = RemoteAudioProcessor()
    else:
        viseme_processor = VisemeProcessor()

    context = LLMContext(messages=training.history() if training else [])
    if training:
        from pipecat.adapters.schemas.function_schema import FunctionSchema
        from pipecat.adapters.schemas.tools_schema import ToolsSchema

        async def advance_stage(params):
            result = await training.advance(params.arguments.get("stage_id"), params.arguments.get("evidence"), params.tool_call_id)
            await params.result_callback(result)

        context.set_tools(ToolsSchema(standard_tools=[FunctionSchema(
            name="advance_stage", description="Подтвердить цель этапа цитатой участника и обновить состояние. В гибком сценарии можно отметить цель из любого этапа.",
            properties={"stage_id": {"type": "string"}, "evidence": {"type": "string"}},
            required=["stage_id", "evidence"], handler=advance_stage,
        )]))
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=make_user_aggregator_params(fast_interrupt=True) if remote else make_user_aggregator_params(),
    )
    if training:
        @user_aggregator.event_handler("on_user_turn_message_added")
        async def user_message(aggregator, message):
            await training.user_message(message.content)

        @assistant_aggregator.event_handler("on_assistant_turn_stopped")
        async def assistant_message(aggregator, message):
            await training.assistant_message(message.content, message.interrupted)

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            user_aggregator,
            llm,
            tts,
            viseme_processor,
            transport.output(),
            assistant_aggregator,
        ]
    )

    from backend.app.training_usage import TrainingUsageObserver
    usage = TrainingUsageObserver(training, llm) if training else None
    worker = PipelineWorker(
        pipeline,
        observers=[usage] if usage else [],
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        idle_timeout_secs=runner_args.pipeline_idle_timeout_secs,
    )

    runner = WorkerRunner(handle_sigint=runner_args.handle_sigint)
    if training:
        training.worker = worker
    await runner.add_workers(worker)

    @worker.rtvi.event_handler("on_client_ready")
    async def on_client_ready(rtvi):
        logger.info("Client ready event received")
        if training:
            greeting = training.session.scenario.stages[0].opening_line if not training.session.turns else "Продолжим наш разговор."
            await worker.queue_frames([TTSSpeakFrame(greeting)])
        else:
            context.add_message({"role": "developer", "content": "Start by introducing yourself."})
            await worker.queue_frames([LLMRunFrame()])

    if remote:
        @worker.rtvi.event_handler("on_client_message")
        async def presentation_event(rtvi, message):
            if message.type == "interrupt":
                await worker.flush_pipeline()
            elif message.type == "playback_metric" and isinstance(message.data, dict):
                # Only bounded numeric diagnostics, never arbitrary client text or prompts.
                kind, value = message.data.get("kind"), message.data.get("ms")
                if kind in {"handoff_to_audio", "vad_event_to_mute", "video_connect"} and isinstance(value, (int, float)) and 0 <= value <= 180000:
                    async with training.service.locks[training.sid]:
                        session = training.session
                        session.voice_metrics.append({"kind": kind, "ms": round(value),
                            "profile": session.settings.avatar_profile, "audio_only": getattr(training, "audio_only", False)})
                        session.voice_metrics = session.voice_metrics[-100:]
                        training.service.save(session)

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Client connected")

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Client disconnected")
        await runner.cancel()

    try:
        await runner.run()
    finally:
        if usage:
            usage.finish_unknown()


async def bot(runner_args: RunnerArguments):
    transport = await create_transport(runner_args, transport_params)
    await run_bot(transport, runner_args)


if __name__ == "__main__":
    from pipecat.runner.run import main

    main()
