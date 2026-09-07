import asyncio
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from backend.text_app.agent import Agent, AgentError
from backend.text_app.budget import OpenAIRequestBudget, OpenAIUnavailable
from backend.text_app.models import Session, Settings
from backend.text_app.seeds import seed
from backend.text_app.store import Store
from backend.text_app.usage import cost_nano_usd, token_usage


USAGE = {'prompt_tokens': 1000, 'completion_tokens': 200, 'total_tokens': 1200,
         'prompt_tokens_details': {'cached_tokens': 400, 'cache_write_tokens': 100},
         'completion_tokens_details': {'reasoning_tokens': 50}}


def ledger(tmp_path, **kwargs):
    return OpenAIRequestBudget('synthetic-key', enabled=True, path=tmp_path / 'usage.sqlite3', **kwargs)


def test_exact_cost_subsets_and_unknown_prices():
    parsed = token_usage(USAGE)
    # (500*.2 + 400*.02 + 100*.25 + 200*1.2) / 1M = $0.000373.
    assert cost_nano_usd('gpt-5.6-luna', parsed) == 373000
    assert cost_nano_usd('unknown', parsed) is None
    assert cost_nano_usd('gpt-5.6-luna', parsed, standard_openai=False) is None
    plain = token_usage({'prompt_tokens': 1000, 'completion_tokens': 200, 'total_tokens': 1200})
    assert cost_nano_usd('gpt-4.1-mini-2025-04-14', plain) == 720000


def test_long_context_surcharge():
    parsed = token_usage({'prompt_tokens': 272001, 'completion_tokens': 100, 'total_tokens': 272101})
    assert cost_nano_usd('gpt-5.6-luna', parsed) == 108980400


@pytest.mark.parametrize('invalid', [None, {}, 'bad', {'prompt_tokens': 1, 'completion_tokens': 2},
    {**USAGE, 'total_tokens': 0}, {**USAGE, 'prompt_tokens': True},
    {**USAGE, 'prompt_tokens_details': {'cached_tokens': 1200}},
    {**USAGE, 'completion_tokens_details': {'reasoning_tokens': -1}}])
def test_incomplete_usage_is_not_zero(invalid):
    assert token_usage(invalid) is None


def test_persistence_idempotency_unknown_and_old_rows(tmp_path):
    budget = ledger(tmp_path)
    rid = budget.reserve('text_turn')
    budget.record(rid, 'gpt-5.6-luna', USAGE)
    budget.record(rid, 'gpt-5.6-luna', USAGE)
    budget.finish(rid, 'completed')
    budget.reserve('text_report')
    with sqlite3.connect(tmp_path / 'usage.sqlite3') as db:
        db.execute("INSERT INTO reservations(reservation_id,operation) VALUES ('old','text_turn'),('audio','tts')")
    status = ledger(tmp_path).status()
    assert status['unlimited'] and status['remaining_requests'] is None
    assert status['used_requests'] == 3
    u = status['usage']
    assert u['total_tokens'] == 1200 and u['estimated_cost_usd'] == .000373
    assert u['unmeasured_requests'] == u['unpriced_requests'] == 2
    assert 'synthetic-key' not in json.dumps(status)


def test_unlimited_concurrent_reservations_and_disabled_guard(tmp_path):
    budget = ledger(tmp_path, max_requests=1)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: budget.reserve('text_turn'), range(30)))
    assert budget.used_requests() == 30
    budget.enabled = False
    with pytest.raises(OpenAIUnavailable, match='выключен'):
        budget.reserve('text_turn')


def test_no_measurements_no_zero_cost(tmp_path):
    budget = ledger(tmp_path)
    budget.reserve('text_turn')
    assert budget.status()['usage']['estimated_cost_usd'] is None


@pytest.mark.parametrize('tier,base', [('priority','https://api.openai.com/v1'), ('default','https://proxy.invalid/v1')])
def test_unverified_tariff_still_records_tokens(tmp_path, tier, base):
    budget = ledger(tmp_path, base_url=base)
    rid = budget.reserve('text_turn')
    budget.record(rid, 'gpt-5.6-luna', USAGE, tier)
    assert budget.status()['usage']['total_tokens'] == 1200
    assert budget.status()['usage']['estimated_cost_usd'] is None


def session(tmp_path):
    store = Store(tmp_path / 'scenarios.sqlite3')
    seed(store)
    return Session(id='synthetic', participant='Тест', consent=True, scenario=store.scenario('sales-objection'), settings=Settings())


@pytest.mark.parametrize('content,finish', [('not json', 'stop'), ('{}', 'length')])
async def test_invalid_model_answer_still_costs(tmp_path, content, finish):
    budget = ledger(tmp_path)
    def response(request):
        assert json.loads(request.content)['service_tier'] == 'default'
        return httpx.Response(200, json={'model': 'gpt-5.6-luna', 'usage': USAGE,
            'choices': [{'finish_reason': finish, 'message': {'content': content}}]})
    agent = Agent(budget, httpx.MockTransport(response))
    with pytest.raises(AgentError):
        await agent.turn(session(tmp_path))
    assert budget.status()['usage']['estimated_cost_usd'] == .000373
    assert budget.status()['usage']['recent'][0]['state'] == 'failed'


async def test_cancel_counts_attempt_without_inventing_usage(tmp_path):
    budget = ledger(tmp_path)
    entered = asyncio.Event()
    async def response(request):
        entered.set()
        await asyncio.Event().wait()
    agent = Agent(budget, httpx.MockTransport(response))
    task = asyncio.create_task(agent.turn(session(tmp_path)))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert budget.status()['usage']['recent'][0]['state'] == 'cancelled'
    assert budget.status()['usage']['estimated_cost_usd'] is None
