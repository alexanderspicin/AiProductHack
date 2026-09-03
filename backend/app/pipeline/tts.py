from pipecat.services.inworld.tts import InworldTTSService
from pipecat.transcriptions.language import Language

from app.config import settings


def make_tts() -> InworldTTSService:
    return InworldTTSService(
        api_key=settings.inworld_api_key,
        settings=InworldTTSService.Settings(
            voice=settings.inworld_voice_id,
            language=Language.RU,
        ),
    )
