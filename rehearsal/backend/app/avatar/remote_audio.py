"""Forward generated PCM immediately, independently of the transport playout clock.

Pipecat still owns input, turn detection, generation, usage and conversation context.
Binary transport audio is ignored by remote-avatar clients to avoid double playback.
"""
import base64
from collections import deque

from pipecat.frames.frames import InterruptionFrame, TTSStartedFrame, TTSStoppedFrame, TTSAudioRawFrame, ErrorFrame
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.processors.frameworks.rtvi import RTVIServerMessageFrame


class RemoteAudioProcessor(FrameProcessor):
    def __init__(self):
        super().__init__()
        self.epoch = 0
        self.sequence = 0
        self.context_id = None
        self.active = False
        self.retired = deque(maxlen=256)

    async def emit(self, kind, **data):
        await self.push_frame(RTVIServerMessageFrame(data={"type": "avatar_audio", "kind": kind,
            "epoch": self.epoch, "sequence": self.sequence, **data}))

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if direction != FrameDirection.DOWNSTREAM:
            await self.push_frame(frame, direction)
            return
        if isinstance(frame, InterruptionFrame):
            if self.context_id is not None:
                self.retired.append(self.context_id)
            self.active = False
            self.context_id = None
            self.epoch += 1
            await self.emit("interrupt")
        elif isinstance(frame, TTSStartedFrame):
            if frame.context_id is not None and frame.context_id in self.retired:
                return
            self.sequence += 1
            self.context_id = frame.context_id
            self.active = True
            await self.emit("start")
        elif isinstance(frame, TTSAudioRawFrame):
            if not self.active or (frame.context_id is not None and frame.context_id != self.context_id):
                return
            if frame.sample_rate != 24000 or frame.num_channels != 1 or len(frame.audio) % 2:
                await self.push_frame(ErrorFrame("Неверный формат звука для видео: нужен PCM16 mono 24 kHz.", fatal=True))
                return
            # Bound individual messages and avoid waiting for a whole utterance.
            for offset in range(0, len(frame.audio), 4800):
                await self.emit("chunk", audio=base64.b64encode(frame.audio[offset:offset + 4800]).decode("ascii"))
        elif isinstance(frame, TTSStoppedFrame):
            if not self.active or (frame.context_id is not None and frame.context_id != self.context_id):
                return
            self.active = False
            await self.emit("end")
        await self.push_frame(frame, direction)
