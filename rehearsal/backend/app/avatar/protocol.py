"""Avatar sidecar event schema, sent to the browser via RTVIServerMessageFrame.

Minimal by design (see project plan): rula's full turn_id/generation_id/branch_state
state machine is not needed here because Pipecat's own interruption handling already
manages turn/generation cancellation. The only thing the frontend needs from us is a
monotonically increasing utterance_id so it can discard stale viseme events after an
interrupt.
"""

from typing import Literal, NotRequired, TypedDict


class VisemeEvent(TypedDict):
    type: Literal["viseme"]
    utterance_id: int
    audio_offset_ms: NotRequired[float]
    mouth_open: float  # 0.0 - 1.0, derived from blendshapes["jawOpen"]
    # ARKit-named blendshape weights (0.0-1.0) from the local spectral viseme
    # analysis (see app/avatar/viseme_analysis.py). Always present on real events.
    blendshapes: NotRequired[dict[str, float]]


class PlaybackStartEvent(TypedDict):
    type: Literal["playback_start"]
    utterance_id: int


class PlaybackEndEvent(TypedDict):
    type: Literal["playback_end"]
    utterance_id: int


class InterruptEvent(TypedDict):
    type: Literal["interrupt"]
    utterance_id: int


AvatarEvent = VisemeEvent | PlaybackStartEvent | PlaybackEndEvent | InterruptEvent


def viseme(
    utterance_id: int, mouth_open: float, blendshapes: dict[str, float] | None = None, audio_offset_ms: float = 0
) -> VisemeEvent:
    event: VisemeEvent = {"type": "viseme", "utterance_id": utterance_id, "mouth_open": mouth_open}
    event["audio_offset_ms"] = audio_offset_ms
    if blendshapes is not None:
        event["blendshapes"] = blendshapes
    return event


def playback_start(utterance_id: int) -> PlaybackStartEvent:
    return {"type": "playback_start", "utterance_id": utterance_id}


def playback_end(utterance_id: int) -> PlaybackEndEvent:
    return {"type": "playback_end", "utterance_id": utterance_id}


def interrupt(utterance_id: int) -> InterruptEvent:
    return {"type": "interrupt", "utterance_id": utterance_id}
