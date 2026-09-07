"""One short, explicitly requested API smoke test; records actual token usage."""
import asyncio
import json
import time

from openai import AsyncOpenAI
from backend.text_app.budget import OpenAIRequestBudget
from backend.text_app.models import Settings


async def main():
    budget = OpenAIRequestBudget.from_local_config()
    reservation = budget.reserve("text_turn")
    model = Settings().model
    started = time.perf_counter()
    first_ms, text, usage = None, "", None
    try:
        async with AsyncOpenAI(api_key=budget.api_key, base_url=budget.base_url, max_retries=0, timeout=20) as client:
            stream = await client.chat.completions.create(model=model, messages=[{"role": "user", "content": "Ответь по-русски одним коротким предложением: готов к тренировке?"}],
                max_completion_tokens=40, reasoning_effort="none", stream=True, stream_options={"include_usage": True})
            async for chunk in stream:
                if chunk.usage:
                    usage = chunk.usage.model_dump()
                    budget.record(reservation, chunk.model or model, usage)
                if chunk.choices and chunk.choices[0].delta.content:
                    if first_ms is None:
                        first_ms = round((time.perf_counter() - started) * 1000)
                    text += chunk.choices[0].delta.content
        budget.finish(reservation, "completed")
        print(json.dumps({"model": model, "text": text, "first_token_ms": first_ms,
                          "total_ms": round((time.perf_counter() - started) * 1000), "usage": usage}, ensure_ascii=False, indent=2))
    except Exception as exc:
        budget.finish(reservation, "failed")
        print(json.dumps({"error_type": type(exc).__name__, "http_status": getattr(exc, "status_code", None)}))
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
