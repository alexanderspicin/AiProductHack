from pipecat.services.whisper.stt import WhisperSTTService
from pipecat.transcriptions.language import Language

from backend.app.config import settings


def make_stt() -> WhisperSTTService:
    """Local speech-to-text via faster-whisper. No API key required.

    device="cuda" + compute_type="float16" runs the ctranslate2 backend on GPU
    (confirmed available: ctranslate2.get_cuda_device_count() == 1 on this machine).
    """
    return WhisperSTTService(
        model=settings.whisper_model,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
        language=Language.RU,
    )
