from pipecat.services.openai.llm import OpenAILLMService

from app.config import settings

SYSTEM_INSTRUCTION = (
    "You are a friendly, helpful voice assistant with a VRM avatar body.Use Russian language "
    "Your output will be converted to audio, so don't include special characters "
    "or markdown in your answers. Keep responses brief and conversational — "
    "one or two sentences at most."
)


def make_llm() -> OpenAILLMService:
    return OpenAILLMService(
        api_key=settings.openai_api_key,
        settings=OpenAILLMService.Settings(
            system_instruction=SYSTEM_INSTRUCTION,
            model='gpt-4o-mini'
        ),
    )
