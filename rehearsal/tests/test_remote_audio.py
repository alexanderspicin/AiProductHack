"""No cloud calls: exact PCM generation boundaries and cancellation semantics."""
from unittest.mock import AsyncMock

import pytest

pytest.importorskip('pipecat')


async def test_pcm_is_immediate_bounded_and_cancelled_context_never_reopens(monkeypatch):
    from backend.app.avatar.remote_audio import RemoteAudioProcessor
    from pipecat.frames.frames import TTSStartedFrame, TTSAudioRawFrame, InterruptionFrame, TTSStoppedFrame
    from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
    from pipecat.processors.frameworks.rtvi import RTVIServerMessageFrame
    monkeypatch.setattr(FrameProcessor, 'process_frame', AsyncMock())
    p = RemoteAudioProcessor(); p.push_frame = AsyncMock()
    async def push(frame): await p.process_frame(frame, FrameDirection.DOWNSTREAM)
    await push(TTSStartedFrame(context_id='one'))
    await push(TTSAudioRawFrame(audio=b'\x00\x01' * 3000, sample_rate=24000, num_channels=1, context_id='one'))
    events = [c.args[0].data for c in p.push_frame.call_args_list if isinstance(c.args[0], RTVIServerMessageFrame)]
    assert [e['kind'] for e in events] == ['start', 'chunk', 'chunk']
    assert len(events[1]['audio']) == 6400
    await push(InterruptionFrame())
    await push(TTSStartedFrame(context_id='one'))
    await push(TTSAudioRawFrame(audio=b'\0\0', sample_rate=24000, num_channels=1, context_id='one'))
    await push(TTSStoppedFrame(context_id='one'))
    await push(TTSStartedFrame(context_id='two'))
    await push(TTSAudioRawFrame(audio=b'\0\0', sample_rate=24000, num_channels=1, context_id='one'))
    await push(TTSAudioRawFrame(audio=b'\0\0', sample_rate=24000, num_channels=1, context_id='two'))
    events = [c.args[0].data for c in p.push_frame.call_args_list if isinstance(c.args[0], RTVIServerMessageFrame)]
    assert [e['kind'] for e in events] == ['start','chunk','chunk','interrupt','start','chunk']
    assert events[-1]['epoch'] == 1 and events[-1]['sequence'] == 2


async def test_selected_pipeline_uses_cartesia_and_no_viseme_processor(monkeypatch, tmp_path):
    from backend.app import bot
    from backend.text_app.voice_training import VoiceTraining
    from backend.text_app.models import Settings, StartRequest
    from backend.text_app.agent import Agent
    from backend.text_app.budget import OpenAIRequestBudget
    from backend.text_app.main import create_app
    from backend.text_app.store import Store
    from pipecat.processors.frame_processor import FrameProcessor
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    store = Store(tmp_path / 'db')
    app = create_app(store=store, agent=Agent(OpenAIRequestBudget(path=tmp_path / 'usage')))
    app.state.service.agent.opening = AsyncMock(return_value='Здравствуйте. Давайте обсудим ситуацию.')
    store.put('settings', 'main', Settings(voice_mode='avatar', avatar_profile='anam_tatiana'))
    s = await app.state.service.start(StartRequest(scenario_id='sales-objection', request_id='selected-pipeline-test', consent=True, voice_consent=True))
    training = VoiceTraining(app.state.service, s.id)
    monkeypatch.setattr(bot, 'make_stt', FrameProcessor)
    monkeypatch.setattr(bot, 'make_llm', lambda **kw: FrameProcessor())
    cartesia = MagicMock(return_value=FrameProcessor()); monkeypatch.setattr(bot, 'make_cartesia', cartesia)
    old_tts = MagicMock(); monkeypatch.setattr(bot, 'make_tts', old_tts)
    transport = MagicMock(); transport.input.return_value = FrameProcessor(); transport.output.return_value = FrameProcessor()
    runner = SimpleNamespace(add_workers=AsyncMock(), run=AsyncMock(), cancel=AsyncMock())
    monkeypatch.setattr(bot, 'WorkerRunner', lambda **kw: runner)
    parts = []; original = bot.Pipeline
    def pipeline(p): parts.extend(p); return original(p)
    monkeypatch.setattr(bot, 'Pipeline', pipeline)
    await bot.run_bot(transport, SimpleNamespace(handle_sigint=False, pipeline_idle_timeout_secs=300), training)
    cartesia.assert_called_once_with('anam_tatiana'); old_tts.assert_not_called()
    assert type(parts[5]).__name__ == 'RemoteAudioProcessor'
    assert type(parts[2]).__name__ == 'LLMUserAggregator'
