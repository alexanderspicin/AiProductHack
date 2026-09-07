import type { Session } from './types'
import { Icon } from './ui'

export function observedStageIds(session: Session): Set<string> {
  return new Set(session.progress_mode === 'flexible'
    ? (session.stage_progress || []).map(g => g.stage_id)
    : session.scenario.stages.filter((_, i) => i < session.stage_index).map(s => s.id))
}

export function TrainingPlan({ session, onDetails, expanded }: { session: Session; onDetails: () => void; expanded: boolean }) {
  const observed = observedStageIds(session)
  return <nav className="conversation-plan" aria-label="Краткий план разговора">
    <span className="plan-caption">План разговора</span>
    <ol>{session.scenario.stages.map((stage, i) => <li key={stage.id}>
      <button className={observed.has(stage.id) ? 'is-observed' : ''} onClick={onDetails} aria-controls="conversation-task" aria-expanded={expanded} aria-label={`${i + 1}. ${stage.title}${observed.has(stage.id) ? '. Обсуждено' : ''}. Открыть задание`}>
        <span className="plan-marker" aria-hidden="true">{observed.has(stage.id) ? <Icon name="check" size={13} /> : i + 1}</span><span>{stage.title}</span>
      </button>
    </li>)}</ol>
  </nav>
}
