import httpx

from backend.text_app.agent import Agent
from backend.text_app.budget import OpenAIRequestBudget
from backend.text_app.main import create_app
from backend.text_app.store import Store


async def test_complete_demo_without_credentials_or_external_requests(tmp_path):
    def reject_external(request):
        raise AssertionError("Demo must not contact external providers")

    budget = OpenAIRequestBudget(path=tmp_path / "budget.sqlite3")
    app = create_app(store=Store(tmp_path / "workspace.sqlite3"), agent=Agent(budget, httpx.MockTransport(reject_external)))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        data = (await client.get('/api/text/bootstrap?role=admin')).json()
        assert not data['budget']['key_configured']
        settings = {**data['settings'], 'provider': 'demo'}
        assert (await client.put('/api/text/settings', json=settings)).status_code == 200
        started = await client.post('/api/text/sessions', json={'scenario_id': 'sales-objection', 'participant': 'Учебный участник', 'request_id': 'demo-start-test'})
        assert started.status_code == 200
        session = started.json()
        for i in range(4):
            turn = await client.post(f"/api/text/sessions/{session['id']}/turns", json={'text': 'Что для вас важно в результате?', 'request_id': f'demo-turn-{i:02}'})
            assert turn.status_code == 200
            session = turn.json()
        assert session['status'] == 'completed'
        report = await client.post(f"/api/text/sessions/{session['id']}/end")
        assert report.status_code == 200
        assert report.json()['report']['overall_score'] is None
        assert report.json()['report_status'] == 'ready'
        assert budget.used_requests() == 0
