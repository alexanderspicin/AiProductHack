"""Local (on-device) turn detection: VAD for turn-start, Smart Turn v3 ONNX model for turn-end.

Pipecat's default stop strategy is already TurnAnalyzerUserTurnStopStrategy(LocalSmartTurnAnalyzerV3),
so this module mainly exists to make the choice explicit and give us a place to tune it.
"""

from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.processors.aggregators.llm_response_universal import LLMUserAggregatorParams
from pipecat.turns.user_stop import TurnAnalyzerUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies


def make_user_aggregator_params() -> LLMUserAggregatorParams:
    vad_analyzer = SileroVADAnalyzer(params=VADParams(stop_secs=0.2))
    # Smart Turn's own stop_secs defaults to 3.0s -- that's the hard fallback timeout
    # used when the model keeps classifying the utterance as INCOMPLETE (e.g. it
    # doesn't recognize a full sentence yet), and 3s of dead air before the bot
    # responds reads as sluggish in casual conversation. 1.2s is a more responsive
    # balance; still enough not to cut off a normal mid-sentence breath pause.
    turn_analyzer = LocalSmartTurnAnalyzerV3(params=SmartTurnParams(stop_secs=1.2))

    return LLMUserAggregatorParams(
        vad_analyzer=vad_analyzer,
        user_turn_strategies=UserTurnStrategies(
            stop=[TurnAnalyzerUserTurnStopStrategy(turn_analyzer=turn_analyzer)],
        ),
        # The actual bottleneck: Smart Turn v3 seems tuned for English prosody and
        # keeps classifying Russian utterances as INCOMPLETE, so
        # TurnAnalyzerUserTurnStopStrategy never fires on its own -- turn completion
        # ends up depending entirely on this separate watchdog fallback (fires when
        # no VAD/transcription activity resets it), not on stop_secs above. Default
        # is 5.0s, which is what actually produced the multi-second stalls after
        # interruption. Lowered to match the stop_secs tuning's intent.
        user_turn_stop_timeout=1.5,
    )
