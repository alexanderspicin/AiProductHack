import type { Scenario } from './types'

/** Public facts only. Private character context belongs on the server. */
export function TrainingBrief({ scenario: s }: { scenario: Scenario }) {
  // Older scenarios describe the employee in third person. Keep the stored text intact.
  const task = s.description.replace(/^Сотрудник должен\s+/u, '')
  return <section className="training-brief" aria-label="Ситуация перед разговором">
    <p className="brief-eyebrow">Перед разговором</p>
    <h2>{s.situation ? 'Что произошло' : 'Ваша задача'}</h2>
    <p>{s.situation || task}</p>
    <dl><div><dt>Вы</dt><dd>{s.employee_role}</dd></div><div><dt>Собеседник</dt><dd>{s.npc_name}, {s.npc_role}</dd></div></dl>
    {s.situation && <p className="brief-task"><b>Ваша задача:</b> {task}</p>}
    <p className="brief-footnote">Отвечайте от своей роли, как в рабочем разговоре. Разбор будет после завершения.</p>
  </section>
}
