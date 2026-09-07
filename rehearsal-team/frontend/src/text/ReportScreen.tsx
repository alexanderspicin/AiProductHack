import { useEffect, useState } from 'react'
import { api, date } from './api'
import type { Session } from './types'
import { Badge, ErrorNotice, Icon, useUnsavedChanges } from './ui'

export function reportMarkdown(session: Session) {
  const r = session.report
  const lines = [`# ${session.scenario.title}`, '', `Участник: ${session.participant}`, `Дата: ${date(session.created_at)}`, `Версия сценария: ${session.scenario.revision}`, `Режим: ${session.is_demo ? 'демонстрация, без LLM' : session.mode === 'practice' ? 'практика' : 'проверка'}`, '', '## Разбор', '', r?.summary || 'Автоматический разбор пока не сформирован.', '', r?.warning || session.report_error,
    '', `Оценка: ${r?.overall_score == null ? 'не выставлена' : `${r.overall_score} / 100`}`, `Охват: ${r?.covered || 0} / ${session.scenario.criteria.length}`, '']
  for (const g of r?.criteria || []) {
    lines.push(`### ${session.scenario.criteria.find(c => c.id === g.criterion_id)?.title || g.criterion_id}`, '', `Балл: ${g.score === null ? 'нет наблюдений' : `${g.score} / 5`}`, g.comment, ...g.evidence.map(e => `Цитата участника: «${e.quote}»`), `Рекомендация: ${g.recommendation}`, '')
  }
  if (session.progress_mode === 'flexible') {
    lines.push('## Что обсудили по плану', '', 'Предварительные наблюдения, не оценка навыков.', '')
    for (const stage of session.scenario.stages) {
      const proof = session.stage_progress?.find(g => g.stage_id === stage.id)
      lines.push(`- ${stage.title}: ${proof ? `обсуждено. Цитата: «${proof.quote}»` : 'нет подтверждения'}`)
    }
    lines.push('')
  }
  lines.push('## Комментарий методиста', '', session.review_note || 'Пока нет комментария.', `Проверено: ${session.reviewed ? 'да' : 'нет'}`, '', '## Стенограмма', '', `${session.scenario.npc_name}: ${session.opening_message}`, '')
  for (const t of session.turns) lines.push(`Участник [${t.status}]: ${t.user_text}`, ...(t.reply ? [`${session.scenario.npc_name}: ${t.reply}`] : []), '')
  return lines.join('\n')
}

export function ReportScreen({ initial, staff, onChange }: { initial: Session; staff: boolean; onChange: () => void }) {
  const [session, setSession] = useState(initial)
  const [tab, setTab] = useState<'report' | 'transcript'>('report')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [note, setNote] = useState(initial.review_note)
  const [reviewed, setReviewed] = useState(initial.reviewed)
  const [saved, setSaved] = useState(false)
  const reviewDirty = staff && (note.trim() !== session.review_note || reviewed !== session.reviewed)
  useUnsavedChanges(reviewDirty)
  useEffect(() => {
    if (session.report_status !== 'pending') return
    let active = true
    const timer = window.setInterval(() => { void api<Session>(`/sessions/${session.id}`).then(s => { if (active) setSession(s) }).catch(() => {}) }, 1200)
    return () => { active = false; clearInterval(timer) }
  }, [session.id, session.report_status])
  const generate = async () => {
    setBusy(true); setError('')
    try { setSession(await api<Session>(`/sessions/${session.id}/${session.report_status === 'failed' ? 'report' : 'end'}`, 'POST')); onChange() }
    catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  const saveReview = async () => {
    if (busy) return
    setBusy(true); setError(''); setSaved(false)
    try { setSession(await api<Session>(`/sessions/${session.id}/review`, 'PUT', { note, reviewed })); setSaved(true); onChange() }
    catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  const download = () => {
    const url = URL.createObjectURL(new Blob([reportMarkdown(session)], { type: 'text/markdown;charset=utf-8' }))
    const a = document.createElement('a'); a.href = url; a.download = `rehearsal-${session.id.slice(0, 8)}.md`; a.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  const r = session.report
  return <>
    <a className="back-link" href="#/results"><Icon name="back" size={17} />История тренировок</a>
    <div className="page-heading"><div><div className="heading-badges"><Badge tone={session.reviewed ? 'green' : 'amber'}>{session.reviewed ? 'Проверено методистом' : 'Нужна проверка методиста'}</Badge>{session.is_demo && <Badge>Демонстрация</Badge>}</div><h1>Разбор тренировки</h1><p>{session.scenario.title} · {session.participant} · {date(session.created_at)}</p></div><div className="button-row"><button className="button secondary" onClick={download}><Icon name="download" size={17} />Скачать</button><a className="button primary" href={`#/scenario/${session.scenario.id}`}>Попробовать ещё раз<Icon name="refresh" size={17} /></a></div></div>
    {error && <ErrorNotice message={error} clear={() => setError('')} />}
    <div className="report-tabs" role="tablist" aria-label="Результат тренировки"><button role="tab" aria-selected={tab === 'report'} onClick={() => setTab('report')} className={tab === 'report' ? 'active' : ''}><Icon name="chart" size={18} />Разбор</button><button role="tab" aria-selected={tab === 'transcript'} onClick={() => setTab('transcript')} className={tab === 'transcript' ? 'active' : ''}><Icon name="chat" size={18} />Стенограмма<span className="tab-count">{session.turns.filter(t => t.status === 'committed').length}</span></button></div>
    {tab === 'report' ? <div className="report-layout"><section>
      {!r ? <div className="report-placeholder"><h2>{busy || session.report_status === 'pending' ? 'Готовим разбор разговора' : session.report_status === 'failed' ? 'Автоматический разбор не получен' : 'Разговор сохранён'}</h2><p>{session.report_error || 'Модель сопоставит ответы с критериями методиста и приведёт цитаты из вашей переписки.'}</p>{!busy && session.report_status !== 'pending' && <button className="button primary" onClick={() => void generate()}>{session.report_status === 'failed' ? 'Повторить разбор · 1 запрос API' : session.is_demo ? 'Открыть итог демо' : 'Сформировать разбор · 1 запрос API'}</button>}<p className="panel-footnote">Стенограмма доступна независимо от работы модели.</p></div> : <>
        <section className="report-summary"><div className="score-circle"><strong className="numeric">{r.overall_score === null ? '—' : r.overall_score}</strong><span>{r.overall_score === null ? 'без оценки' : 'из 100'}</span></div><div><h2>{r.overall_score === null ? 'Готово к разбору с методистом' : 'Есть материал для следующего шага'}</h2><p>{r.summary}</p><span className="coverage">Оценено {r.covered} из {r.total} критериев</span></div></section>
        <div className="notice compact"><Icon name="info" size={18} /><span>{r.warning}</span></div>
        <h2 className="criteria-heading">По каждому критерию</h2><div className="grade-list">{r.criteria.map(g => { const criterion = session.scenario.criteria.find(c => c.id === g.criterion_id); return <details className="grade-item" key={g.criterion_id} open><summary><span>{criterion?.title || g.criterion_id}</span><span className={`grade-score ${g.score !== null && g.score >= 4 ? 'good' : ''}`}>{g.score === null ? 'Нет наблюдений' : `${g.score} / 5`}</span><Icon name="down" size={17} /></summary><div className="grade-body"><p>{g.comment}</p>{g.evidence.map((e, index) => <blockquote key={index}><span>Ваша реплика</span><p>«{e.quote}»</p><button className="text-button" onClick={() => { setTab('transcript'); window.setTimeout(() => document.getElementById(`turn-${e.turn_id}`)?.scrollIntoView({ block: 'center' }), 50) }}>Показать в разговоре</button></blockquote>)}{g.recommendation && <div className="recommendation"><strong>Что попробовать</strong><p>{g.recommendation}</p></div>}<small className="criterion-weight">Вес критерия: {criterion?.weight || 1}</small></div></details> })}</div>
      </>}
      {session.progress_mode === 'flexible' && <section className="report-goals"><h2>Что обсудили по плану</h2><p>Предварительные отметки из диалога, не оценка навыков. Качество разбирается по критериям выше.</p><ol>{session.scenario.stages.map(s => { const proof = session.stage_progress?.find(g => g.stage_id === s.id); return <li key={s.id}><strong>{s.title}</strong><span>{proof ? 'Обсуждено' : 'Нет подтверждения'}</span>{proof && <blockquote>«{proof.quote}»</blockquote>}</li> })}</ol></section>}
    </section><aside className="report-side">{r && <><section><h3>Что получилось</h3>{r.strengths.length ? <ul className="feedback-list">{r.strengths.map((s, i) => <li key={i}><Icon name="check" size={17} /><span>{s}</span></li>)}</ul> : <p>Автоматических выводов пока нет. Разберите реплики с методистом.</p>}</section><section><h3>На следующую тренировку</h3>{r.next_steps.length ? <ol className="next-steps">{r.next_steps.map((s, i) => <li key={i}>{s}</li>)}</ol> : <p>Выберите один критерий и попробуйте другой ответ.</p>}</section></>}
      <section className="methodist-review"><h3>Комментарий методиста</h3>{staff ? <><label className="field"><span id="review-note-label" className="sr-only">Комментарий методиста</span><textarea aria-labelledby="review-note-label" rows={5} maxLength={3000} value={note} disabled={busy} placeholder="Что участнику стоит сохранить в своей практике? Над чем поработать?" onChange={e => { setNote(e.target.value); setSaved(false) }} /></label><label className="checkbox-row"><input type="checkbox" checked={reviewed} disabled={busy} onChange={e => { setReviewed(e.target.checked); setSaved(false) }} />Разбор проверен по стенограмме</label><button className="button secondary full" onClick={() => void saveReview()} disabled={busy || !reviewDirty}>Сохранить комментарий</button>{reviewDirty ? <p className="panel-footnote" role="status">Изменения ещё не сохранены и не попадут в скачанный разбор.</p> : saved && <p className="saved-message" role="status">Комментарий сохранён</p>}</> : <p>{session.review_note || 'Пока нет комментария. Методист может дополнить автоматический разбор.'}</p>}</section>
      <small className="report-version">Сценарий, версия {session.scenario.revision}. {session.completion_reason === 'scenario_complete' ? 'Все пункты обсуждены.' : session.completion_reason === 'turn_limit' ? 'Достигнут лимит реплик.' : 'Завершено участником.'}</small>
    </aside></div> : <section className="transcript"><div className="transcript-heading"><h2>Полный разговор</h2><span>{session.turns.length} попыток ответа</span></div><div className="transcript-line"><span>{session.scenario.npc_name}</span><p>{session.opening_message}</p></div>{session.turns.map(t => <div className="transcript-turn" id={`turn-${t.id}`} key={t.id}><div className="transcript-stage">{session.scenario.stages[t.stage_index]?.title}</div><div className="transcript-line user"><span>{session.participant}</span><div><p>{t.user_text}</p>{t.status !== 'committed' && <small>Не включено в оценку: {t.status === 'cancelled' ? 'ответ остановлен' : t.status === 'failed' ? 'ошибка ответа' : 'ожидание ответа'}.</small>}</div></div>{t.reply && <div className="transcript-line"><span>{session.scenario.npc_name}</span><p>{t.reply}</p></div>}</div>)}</section>}
  </>
}
