"""Evidence-backed coverage; the stage pointer follows the first unobserved goal."""
from .models import GoalEvidence, GoalObservation, Session


def covered_stages(session: Session) -> set[str]:
    return {item.stage_id for item in session.stage_progress}


def record_goals(session: Session, observations: list[GoalObservation]) -> list[str]:
    if session.status != "active":
        return []
    known = {stage.id for stage in session.scenario.stages}
    covered = covered_stages(session)
    accepted = []
    for item in observations:
        if item.stage_id not in known or item.stage_id in covered or not item.quote.strip():
            continue
        turn = next((t for t in reversed(session.turns) if t.status == "committed" and item.quote in t.user_text), None)
        if turn is None:
            continue
        session.stage_progress.append(GoalEvidence(stage_id=item.stage_id, quote=item.quote, turn_id=turn.id))
        covered.add(item.stage_id)
        accepted.append(item.stage_id)
    session.stage_index = next((i for i, stage in enumerate(session.scenario.stages) if stage.id not in covered), len(session.scenario.stages) - 1)
    return accepted


def progress_context(session: Session) -> dict:
    covered = covered_stages(session)
    return {"goals": [{"id": s.id, "objective": s.objective, "observed": s.id in covered} for s in session.scenario.stages],
            "current_stage": session.scenario.stages[session.stage_index].id}
