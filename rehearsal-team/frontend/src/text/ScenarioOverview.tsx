import type { Scenario } from './types'
import { Badge, Icon } from './ui'

// Shared with the actual participant brief so preview and published view stay aligned.
export function ScenarioOverview({ scenario: s, voice = false }: { scenario: Scenario; voice?: boolean }) {
  return <section className="brief-main">
    <Badge tone="green">{s.category || 'Категория не задана'}</Badge>
    <h1>{s.title || 'Название не заполнено'}</h1>
    {s.situation && <section className="brief-section"><h2>Ситуация перед разговором</h2><p>{s.situation}</p></section>}
    <p className="large-copy">{s.description || 'Задача участника пока не заполнена.'}</p>
    <div className="brief-facts"><span><Icon name="clock" />Около {s.duration_minutes} минут</span><span><Icon name="chat" />{voice ? 'Текст, голос и персонаж' : 'Текстовый диалог'}</span></div>
    <section className="brief-section"><h2>Ваша роль</h2><p>{s.employee_role || 'Роль участника пока не заполнена.'}</p></section>
    <section className="brief-section"><h2>План разговора</h2><p>Краткая последовательность останется на экране во время тренировки. В диалоге с ИИ можно менять порядок и возвращаться к пунктам.</p><ol className="stage-preview">{s.stages.map((stage, i) => <li key={stage.id}><strong>{stage.title || `Этап ${i + 1}: название не заполнено`}</strong><p>{stage.objective || 'Цель этапа пока не заполнена.'}</p></li>)}</ol></section>
    <section className="brief-section"><h2>На что посмотрим в разборе</h2><div className="criterion-tags">{s.criteria.map(c => <span key={c.id}><Icon name="check" size={15} />{c.title || 'Критерий пока не заполнен'}</span>)}</div></section>
  </section>
}
