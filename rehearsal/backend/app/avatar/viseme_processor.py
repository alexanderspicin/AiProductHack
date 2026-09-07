"""Taps outgoing TTS audio/text to drive avatar facial animation, without altering the pipeline.

Sits after the TTS service in the pipeline and passes every frame through
unchanged, emitting RTVIServerMessageFrame sidecar events (delivered to the
browser's onServerMessage callback) alongside the audio.

Two viseme sources:
- Text-driven (primary): Inworld TTS emits word-level timing, which pipecat
  stamps onto each `TTSTextFrame` as a presentation timestamp (`frame.pts`, on
  the pipeline clock). We lay each word's letters onto a running absolute-time
  timeline (viseme_text.py) instead of guessing mouth shape from the audio
  spectrum.
- Spectral analysis (fallback): viseme_analysis.py's classifier, used only for
  utterances where the TTS gave us no word timing at all.

Three bugs, all found from real session logs, fixed here:

1. Inworld can deliver several TTSTextFrames back-to-back before any of their
   audio has played. An earlier version replaced a single "current word"
   schedule on every TTSTextFrame, silently discarding every word but the last
   in such a batch. Fixed by appending onto a timeline instead of replacing.

2. Word timing was anchored to *how much audio had been received*, which runs
   far ahead of playback (confirmed: ~26s of audio received while ~4s had
   played), and word durations were pure per-letter guesses accumulated
   back-to-back with no re-anchoring, so the schedule desynchronised from the
   voice by tens of seconds within one response. Fixed by using each word's
   real PTS as its start time, ticking against the same pipeline clock the
   output transport pages audio out on, and re-fitting each word to end where
   the next one starts (viseme_text.VisemeTimeline).

3. TTSStoppedFrame reaches this processor as soon as *synthesis* finishes --
   several seconds before the audio has finished *playing* (BaseOutputTransport
   holds that frame back until its buffer drains; confirmed: the frame passed
   here ~4s before the transport logged "Bot stopped speaking"). Stopping the
   viseme ticker on it froze viseme events mid-utterance, and the frontend's
   dropped-event safety net (visemeDriver's synthetic jawOpen oscillation, which
   kicks in after 250ms of silence while the bot is still speaking) took over --
   the "fish mouth" flapping for the rest of every utterance. Fixed by treating
   TTSStoppedFrame as end-of-*input* only and letting the ticker run until the
   received audio has actually been paced out, then emitting playback_end.
"""

import asyncio

from loguru import logger
from pipecat.frames.frames import (
    Frame,
    InterruptionFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    TTSTextFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.processors.frameworks.rtvi import RTVIServerMessageFrame
from pipecat.utils.time import nanoseconds_to_seconds

from backend.app.avatar import protocol
from backend.app.avatar.viseme_analysis import LipsyncAnalyzer
from backend.app.avatar.viseme_text import VisemeTimeline, jaw_openness

# 50 Hz. The timeline is continuous, so this is purely how finely we sample it;
# at the old 20 Hz the crossfades read as visible steps ("~5fps" motion).
_TICK_INTERVAL_S = 0.02
# Overall articulation amplitude. The viseme morphs of a Ready Player Me head
# are authored for full, exaggerated shapes, so driving them at weight 1.0 reads
# as a mouth flung open; conversational speech sits well below that.
_VISEME_INTENSITY = 0.66
# Extra ARKit jaw motion layered on top of the Oculus viseme morphs, for
# amplitude variation between wide-open vowels and closed consonants. Deliberately
# subtle -- the viseme morphs already open the mouth themselves.
_JAW_OPEN_SCALE = 0.18
# Keep ticking a little past the estimated end of audio: the estimate is built
# from chunk sizes and the client's own playback lags slightly behind us.
_TAIL_GRACE_S = 0.2


class VisemeProcessor(FrameProcessor):
    def __init__(self):
        super().__init__()
        self._utterance_id = 0
        self._analyzer = LipsyncAnalyzer()
        self._current_fallback_viseme = "sil"
        self._timeline = VisemeTimeline()
        self._word_timing_missing = False

        # Playback-span estimate, on the pipeline clock: audio starts playing
        # about when its first chunk passes through here and lasts as long as
        # the audio we've received.
        self._first_audio_clock_s: float | None = None
        self._received_audio_s = 0.0
        self._input_done = False
        self._ticker_task: asyncio.Task | None = None
        self._pending_subtitles = []

    @property
    def _clock_s(self) -> float:
        return nanoseconds_to_seconds(self.get_clock().get_time())

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TTSStartedFrame):
            self._utterance_id += 1
            self._analyzer = LipsyncAnalyzer()  # fresh temporal state per utterance
            self._current_fallback_viseme = "sil"
            self._timeline = VisemeTimeline()
            self._word_timing_missing = False
            self._first_audio_clock_s = None
            self._received_audio_s = 0.0
            self._input_done = False
            self._pending_subtitles = []
            await self._restart_ticker(direction)
            await self.push_frame(
                RTVIServerMessageFrame(data=protocol.playback_start(self._utterance_id)),
                direction,
            )
        elif isinstance(frame, TTSTextFrame):
            if frame.pts is None:
                # No word timing from this service/utterance -- nothing usable to
                # schedule; the spectral fallback carries the whole utterance.
                if not self._word_timing_missing:
                    self._word_timing_missing = True
                    logger.warning(
                        f"VisemeProcessor[{self._utterance_id}]: TTSTextFrame without pts "
                        "(no word timing) -- falling back to spectral viseme analysis."
                    )
            else:
                start_s = nanoseconds_to_seconds(frame.pts)
                self._timeline.add_word(frame.text, start_s)
                self._pending_subtitles.append((frame.text, start_s))
                await self._send_subtitles(direction)
                logger.debug(
                    f"VisemeProcessor[{self._utterance_id}]: word '{frame.text}' at "
                    f"t={start_s:.3f}s (clock now {self._clock_s:.3f}s), "
                    f"{len(self._timeline.units)} visemes scheduled"
                )
        elif isinstance(frame, TTSAudioRawFrame):
            # Only track arrival + keep the fallback analyzer warmed here. Viseme
            # events are emitted by the ticker, not tied to chunk arrival: chunks
            # arrive from Inworld far faster than real-time playback.
            self._current_fallback_viseme = self._analyzer.process_chunk(frame.audio, frame.sample_rate)
            if self._first_audio_clock_s is None:
                self._first_audio_clock_s = nanoseconds_to_seconds(frame.pts) if frame.pts is not None else self._clock_s
                await self._send_subtitles(direction)
            self._received_audio_s += frame.num_frames / frame.sample_rate
        elif isinstance(frame, TTSStoppedFrame):
            # End of *synthesis*, not of playback -- see module docstring, bug 3.
            self._input_done = True
            self._timeline.flush()
        elif isinstance(frame, InterruptionFrame):
            await self._stop_ticker()
            self._pending_subtitles = []
            await self.push_frame(
                RTVIServerMessageFrame(data=protocol.interrupt(self._utterance_id)),
                direction,
            )

        await self.push_frame(frame, direction)

    async def _send_subtitles(self, direction):
        if self._first_audio_clock_s is None:
            return
        for text, pts in self._pending_subtitles:
            await self.push_frame(RTVIServerMessageFrame(data={
                "type": "subtitle", "utterance_id": self._utterance_id, "text": text,
                "audio_offset_ms": max(0, (pts - self._first_audio_clock_s) * 1000),
            }), direction)
        self._pending_subtitles = []

    async def _restart_ticker(self, direction: FrameDirection) -> None:
        await self._stop_ticker()
        self._ticker_task = self.create_task(self._tick_loop(direction))

    async def _stop_ticker(self) -> None:
        if self._ticker_task is not None:
            task, self._ticker_task = self._ticker_task, None
            await self.cancel_task(task)

    def _playback_finished(self, now_s: float) -> bool:
        if not self._input_done or self._first_audio_clock_s is None:
            return False
        audio_end_s = self._first_audio_clock_s + self._received_audio_s + _TAIL_GRACE_S
        return now_s >= audio_end_s

    async def _tick_loop(self, direction: FrameDirection) -> None:
        utterance_id = self._utterance_id
        while True:
            await asyncio.sleep(_TICK_INTERVAL_S)

            now_s = self._clock_s
            self._timeline.trim_before(now_s)

            scheduled = self._timeline.weights_at(now_s)
            if scheduled:
                weights, source = scheduled, "text"
            elif self._timeline.has_words() and not self._word_timing_missing:
                # We have real word timing and it says nothing is being
                # articulated right now: a pause between words. A closed mouth is
                # correct here -- running the spectral classifier instead is what
                # produced meaningless mouth flapping.
                weights, source = {"sil": 1.0}, "gap"
            else:
                # No word timing at all for this utterance: the spectral
                # classifier only yields one discrete viseme per chunk, so the
                # frontend's smoothing does the interpolation in that case.
                weights, source = {self._current_fallback_viseme: 1.0}, "fallback"

            mouth_open = jaw_openness(weights)
            blendshapes = {
                f"viseme_{viseme}": weight * _VISEME_INTENSITY for viseme, weight in weights.items()
            }
            blendshapes["jawOpen"] = mouth_open * _JAW_OPEN_SCALE

            # trace, not debug: at 50 Hz this is far too chatty for a debug log.
            logger.trace(
                f"VisemeProcessor[{utterance_id}]: t={now_s:.3f}s source={source} "
                + ", ".join(f"{v}={w:.2f}" for v, w in sorted(weights.items()))
            )

            await self.push_frame(
                RTVIServerMessageFrame(data=protocol.viseme(utterance_id, mouth_open, blendshapes,
                    max(0, (now_s - (self._first_audio_clock_s if self._first_audio_clock_s is not None else now_s)) * 1000))),
                direction,
            )

            if self._playback_finished(now_s):
                break

        await self.push_frame(
            RTVIServerMessageFrame(data={**protocol.playback_end(utterance_id), "audio_offset_ms": self._received_audio_s * 1000}), direction
        )
        self._ticker_task = None
