from pipecat.services.inworld.tts import InworldTTSService
from pipecat.transcriptions.language import Language

from backend.app.config import settings


def make_tts(*, api_key=None) -> InworldTTSService:
    return InworldTTSService(
        api_key=api_key or settings.inworld_api_key,
        settings=InworldTTSService.Settings(
            voice=settings.inworld_voice_id,
            language=Language.RU,
        ),
    )


def make_cartesia(profile: str):
    from pipecat.services.cartesia.tts import CartesiaTTSService
    from backend.text_app.avatar_profiles import PROFILES
    from backend.text_app.budget import local_setting
    return CartesiaTTSService(
        api_key=local_setting("CARTESIA_API_KEY"), sample_rate=24000,
        settings=CartesiaTTSService.Settings(model="sonic-3.6", voice=PROFILES[profile]["voice_id"], language=Language.RU),
    )
