"""Six text-only checks against the real start path, using an isolated scenario store."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from time import perf_counter
from uuid import uuid4

from dotenv import dotenv_values

from backend.text_app.agent import Agent
from backend.text_app.budget import OpenAIRequestBudget
from backend.text_app.models import Settings, StartRequest
from backend.text_app.seeds import seed
from backend.text_app.service import Service, session_view
from backend.text_app.store import Store
from backend.text_app.voice_training import VoiceTraining


class TrackedBudget(OpenAIRequestBudget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls = []

    def reserve(self, *args, **kwargs):
        rid = super().reserve(*args, **kwargs)
        self.calls.append(rid)
        return rid


async def main(args):
    values = dotenv_values(args.env)
    for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL"):
        if values.get(name):
            os.environ[name] = values[name]
    os.environ["OPENAI_API_ENABLED"] = "1"
    budget = TrackedBudget.from_local_config()
    result = {"cases": [], "voice_video_calls": 0}
    with tempfile.TemporaryDirectory(prefix="rehearsal-gender-fix-") as temporary:
        store = Store(Path(temporary) / "fixtures.db")
        seed(store)
        service = Service(store, Agent(budget))
        feedback = store.scenario("feedback").stages[0].opening_line
        third_people = 'Анна купила гарнитуру. Олег купил микрофон и сказал: «Я готов».'
        feminine = 'Меня зовут Елена. Я купила лицензию, выбрала тариф «Старт», решила начать пилот и подписала договор. Я готова и довольна. '
        neutral = 'Добрый день. Обсудим отчёт? Олег сказал: «Я уже отправил», а Анна ответила: «Я тоже отправила».'
        for profile, name in (("tavus_sergei", "Даниил"), ("anam_tatiana", "Татьяна")):
            store.put("settings", "main", Settings(voice_mode="avatar", avatar_profile=profile))
            for case, source in (("feedback", feedback), ("own_and_others", feminine + third_people), ("neutral_quotes", neutral)):
                scenario = store.scenario("feedback")
                scenario.stages[0].opening_line = source
                scenario.npc_name = "Елена" if case == "own_and_others" else "Михаил Соколов"
                store.put("scenario", scenario.id, scenario)
                original = scenario.model_dump()
                if case == "feedback":
                    expected = feedback if profile == "tavus_sergei" else feedback.replace("отправил", "отправила")
                elif case == "own_and_others":
                    own = (f'Меня зовут {name}. Я купил лицензию, выбрал тариф «Старт», решил начать пилот и подписал договор. Я готов и доволен. '
                           if profile == "tavus_sergei" else feminine.replace("Елена", name))
                    expected = own + third_people
                else:
                    expected = neutral
                row = {"profile": profile, "case": case, "source": source, "expected": expected}
                try:
                    request = StartRequest(scenario_id=scenario.id, request_id=str(uuid4()), consent=True, voice_consent=True)
                    started = perf_counter()
                    session = await service.start(request)
                    row["elapsed_ms"] = round((perf_counter() - started) * 1000)
                    row["actual"] = session_view(session)["opening_message"]
                    row["exact_expected"] = row["actual"] == expected
                    row["voice_history_same"] = VoiceTraining(service, session.id).history()[0]["content"] == row["actual"]
                    row["source_unchanged"] = store.scenario(scenario.id).model_dump() == original
                    calls = len(budget.calls)
                    started = perf_counter()
                    cached = await service.start(request.model_copy(update={"request_id": str(uuid4())}))
                    row["cache_ms"] = round((perf_counter() - started) * 1000)
                    row["cache_no_request"] = len(budget.calls) == calls
                    row["cache_same"] = cached.scenario.stages[0].opening_line == row["actual"]
                except Exception as exc:
                    row["error_type"] = type(exc).__name__
                result["cases"].append(row)
                args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
                print(json.dumps(row, ensure_ascii=False), flush=True)
                if "error_type" in row:
                    break
            if any("error_type" in r for r in result["cases"]):
                break
    with sqlite3.connect(budget._path) as db:
        rows = [db.execute("SELECT total_tokens,cost_nano_usd,state FROM text_usage WHERE reservation_id=?", (rid,)).fetchone() for rid in budget.calls]
    result["usage"] = {
        "requests": len(rows), "total_tokens": sum(r[0] or 0 for r in rows),
        "estimated_cost_usd": sum(r[1] or 0 for r in rows) / 1_000_000_000,
        "unpriced_requests": sum(r[1] is None for r in rows),
        "completed_requests": sum(r[2] == "completed" for r in rows),
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result["usage"], ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(main(parser.parse_args()))
