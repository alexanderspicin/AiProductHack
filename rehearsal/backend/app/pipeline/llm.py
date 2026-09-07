from pipecat.services.openai.llm import OpenAILLMService

from backend.app.config import settings

SYSTEM_INSTRUCTION = (
    "You are a friendly, helpful voice assistant with a VRM avatar body.Use Russian language "
    "Your output will be converted to audio, so don't include special characters "
    "or markdown in your answers. Keep responses brief and conversational — "
    "one or two sentences at most."
)


def make_llm(*, instruction=SYSTEM_INSTRUCTION, model="gpt-4o-mini", api_key=None, base_url=None) -> OpenAILLMService:
    return OpenAILLMService(
        api_key=api_key or settings.openai_api_key,
        base_url=base_url,
        settings=OpenAILLMService.Settings(
            system_instruction=instruction,
            model=model,
            max_completion_tokens=600,
            extra={"reasoning_effort": "none"} if model == "gpt-5.6-luna" else {},
        ),
    )
