import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { api, id, initials } from './api'
import type { Session } from './types'
import { ErrorNotice, Icon } from './ui'
import { TrainingBrief } from './TrainingBrief'
import { observedStageIds, TrainingPlan } from './TrainingPlan'
import './conversation.css'

const VoiceTools = lazy(() => import('../voice/VoiceTools').then(module => ({ default: module.VoiceTools })))

export function Conversation({ initial, onFinish }: { initial: Session; onFinish: (s: Session) => void }) {
  const [session, setSession] = useState(initial)
  const [text, setText] = useState('')
  const [error, setError] = useState('')
  const [waiting, setWaiting] = useState(initial.turns.some(t => t.status === 'pending'))
  const [finishing, setFinishing] = useState(false)
  const [hint, setHint] = useState(false)
  const [confirmEnd, setConfirmEnd] = useState(false)
  const [voiceConnected, setVoiceConnected] = useState(false)
  const [voiceReady, setVoiceReady] = useState(false)
  const [planOpen, setPlanOpen] = useState(false)
  const voiceStop = useRef<(() => Promise<void>) | null>(null)
  const voiceSend = useRef<((text: string) => Promise<void>) | null>(null)
  const pending = useRef<string | null>(initial.turns.find(t => t.status === 'pending')?.request_id || null)
  const controller = useRef<AbortController | null>(null)
  const epoch = useRef(0)
  const mounted = useRef(true)
  const messages = useRef<HTMLDivElement>(null)
  const input = useRef<HTMLTextAreaElement>(null)
  useEffect(() => {
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape') { setPlanOpen(false); setConfirmEnd(false) } }
    document.addEventListener('keydown', close)
    return () => document.removeEventListener('keydown', close)
  }, [])
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      // React StrictMode immediately mounts the effect again. Only cancel on a real exit.
      queueMicrotask(() => {
        if (mounted.current) return
        epoch.current++; controller.current?.abort()
        if (pending.current) void api(`/sessions/${initial.id}/cancel`, 'POST', { request_id: pending.current }).catch(() => {})
      })
    }
  }, [initial.id])
  useEffect(() => {
    if (messages.current && (session.turns.length || waiting)) messages.current.scrollTop = messages.current.scrollHeight
  }, [session.turns.length, waiting, session.turns.at(-1)?.reply])
  // Restore in-flight state after reload without another generation request.
  useEffect(() => {
    if (!waiting && !voiceConnected) return
    const timer = window.setInterval(() => {
      const version = epoch.current
      void api<Session>(`/sessions/${initial.id}`).then(s => {
        if (!mounted.current || version !== epoch.current) return
        setSession(s)
        if (!s.turns.some(t => t.status === 'pending')) { setWaiting(false); pending.current = null }
      }).catch(() => {})
    }, 1200)
    return () => clearInterval(timer)
  }, [waiting, voiceConnected, initial.id])
  const send = async () => {
    if (!text.trim() || waiting || finishing || session.status !== 'active') return
    if (voiceConnected) {
      if (!voiceSend.current) { setError('Дождитесь подключения голоса.'); return }
      const content = text.trim(); setText(''); setError('')
      try { await voiceSend.current(content) }
      catch (e) { setError((e as Error).message); setText(content) }
      return
    }
    const content = text.trim(), requestId = id(), version = ++epoch.current
    setText(''); setError(''); setWaiting(true); setHint(false)
    pending.current = requestId
    controller.current = new AbortController()
    setSession(s => ({ ...s, turns: [...s.turns, { id: requestId, request_id: requestId, user_text: content, reply: '', stage_index: s.stage_index, status: 'pending', elapsed_ms: null, created_at: new Date().toISOString() }] }))
    try {
      const result = await api<Session>(`/sessions/${session.id}/turns`, 'POST', { text: content, request_id: requestId }, controller.current.signal)
      if (mounted.current && version === epoch.current) setSession(result)
    } catch (e) {
      if (mounted.current && version === epoch.current) {
        setError((e as Error).message)
        setText(current => current || content)
        try { const restored = await api<Session>(`/sessions/${session.id}`); if (version === epoch.current) setSession(restored) } catch { /* Original error remains visible. */ }
      }
    } finally {
      if (mounted.current && version === epoch.current) { pending.current = null; setWaiting(false); input.current?.focus() }
    }
  }
  const cancel = async () => {
    const requestId = pending.current
    if (!requestId) return
    const version = ++epoch.current
    controller.current?.abort(); setWaiting(false); pending.current = null
    setSession(s => ({ ...s, turns: s.turns.map(t => t.request_id === requestId && t.status === 'pending' ? { ...t, status: 'cancelled' } : t) }))
    try { const stopped = await api<Session>(`/sessions/${session.id}/cancel`, 'POST', { request_id: requestId }); if (mounted.current && version === epoch.current) setSession(stopped) }
    catch (e) { if (mounted.current) setError(`Не удалось подтвердить остановку на сервере. ${(e as Error).message}`) }
    input.current?.focus()
  }
  const finish = async () => {
    if (finishing) return
    setConfirmEnd(false); setFinishing(true); setError('')
    if (session.voice_mode === 'avatar') {
      try { if (voiceStop.current) await voiceStop.current(); else await api(`/sessions/${session.id}/voice/stop`, 'POST'); setVoiceConnected(false) }
      catch (e) { setError((e as Error).message); setFinishing(false); return }
    }
    if (pending.current) await cancel()
    try { const result = await api<Session>(`/sessions/${session.id}/end`, 'POST'); if (mounted.current) onFinish(result) }
    catch (e) { if (mounted.current) { setError((e as Error).message); setFinishing(false) } }
  }
  const stage = session.scenario.stages[session.stage_index]
  const observed = observedStageIds(session)
  const liveAvatar = session.voice_mode === 'avatar'
  return <div className={`conversation-layout ${liveAvatar ? 'call-layout' : 'text-layout'}`}>
    <header className="conversation-header"><a className="icon-button" href="#/library" aria-label="К тренировкам"><Icon name="back" /></a><div className="conversation-title"><h1>{session.scenario.title}</h1><p>{session.mode === 'practice' ? 'Практика' : 'Проверка знаний'} · {session.progress_mode === 'flexible' ? `Обсуждено ${observed.size} из ${session.scenario.stages.length}` : `Этап ${session.stage_index + 1} из ${session.scenario.stages.length}`}</p></div><div className="conversation-header-actions"><button className="button secondary small" aria-expanded={planOpen} aria-controls="conversation-task" onClick={() => setPlanOpen(!planOpen)}><Icon name="book" size={17} />Задание</button>{!liveAvatar && <button className="button secondary small" onClick={() => setConfirmEnd(true)} disabled={finishing}>{finishing ? 'Готовим разбор…' : 'Завершить'}</button>}</div></header>
    <TrainingPlan session={session} onDetails={() => setPlanOpen(true)} expanded={planOpen} />
    {planOpen && <aside id="conversation-task" className="training-plan is-drawer" aria-label="Задание тренировки"><div className="section-row"><h2>Задание</h2><button className="icon-button" aria-label="Закрыть задание" onClick={() => setPlanOpen(false)}><Icon name="close" /></button></div><TrainingBrief scenario={session.scenario} /><h2>План разговора</h2>{session.progress_mode === 'flexible' && <p>Порядок поможет начать, но его можно менять. Отметка «Обсуждено» не означает оценку навыка.</p>}<ol>{session.scenario.stages.map((s, index) => <li key={s.id} className={observed.has(s.id) ? 'done' : index === session.stage_index ? 'current' : ''}><span className="stage-number">{observed.has(s.id) ? <Icon name="check" size={13} /> : index + 1}</span><span><b>{s.title}</b><small>{s.objective}</small>{observed.has(s.id) && <small>Обсуждено</small>}</span></li>)}</ol><div className="plan-footer"><span className="numeric">{session.turns.filter(t => t.status === 'committed').length} / {session.max_turns}</span><small>реплик в этой тренировке</small></div></aside>}
    {liveAvatar && <Suspense fallback={<div className="call-loading" role="status">Готовим экран разговора…</div>}><VoiceTools sessionId={session.id} name={session.scenario.npc_name} intro={<TrainingBrief scenario={session.scenario} />} disabled={finishing || session.status !== 'active'} startDisabled={waiting} onConnection={connected => { setVoiceConnected(connected); setVoiceReady(false) }} onReady={() => setVoiceReady(true)} onEnd={() => setConfirmEnd(true)} sendRef={voiceSend} stopRef={voiceStop} /></Suspense>}
    <section className={`chat-panel ${session.voice_mode === 'avatar' && !liveAvatar ? 'has-avatar' : ''}`} aria-label="Диалог">
      <div className="chat-person"><span className="mini-person">{initials(session.scenario.npc_name)}</span><div><strong>{session.scenario.npc_name}</strong><span>{session.scenario.npc_role}</span></div></div>
      {session.is_demo && <div className="notice warning compact">Демонстрация интерфейса. Реплики заготовлены; оценка ИИ выключена.</div>}
      <div className="messages" ref={messages} role="log" aria-label="Переписка" aria-live="polite" aria-relevant="additions text">
        {!liveAvatar && session.turns.length === 0 && <TrainingBrief scenario={session.scenario} />}
        <p className="conversation-start">Начало тренировки · {new Date(session.created_at).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}</p>
        <div className="message assistant"><span className="message-author">{session.scenario.npc_name.split(' ')[0]}</span><p>{session.opening_message}</p></div>
        {session.turns.map(t => <div className="turn-pair" key={t.id}><div className={`message user ${t.status === 'cancelled' || t.status === 'failed' ? 'interrupted' : ''}`}><span className="message-author">Вы</span><p>{t.user_text}</p>{t.status === 'cancelled' && <small>Ответ остановлен. Реплика не вошла в оценку.</small>}{t.status === 'failed' && <small>Ответ не получен. Реплика не вошла в оценку.</small>}</div>{t.status === 'committed' && <div className="message assistant"><span className="message-author">{session.scenario.npc_name.split(' ')[0]}</span><p>{t.reply}</p>{t.interrupted && <small>Собеседник был прерван.</small>}</div>}</div>)}
        {waiting && <div className="typing-status" role="status"><span className="typing-dots"><i /><i /><i /></span>Собеседник отвечает…</div>}
        {session.status === 'completed' && <div className="conversation-end"><Icon name="check" /><div><strong>Разговор завершён</strong><p>{session.completion_reason === 'turn_limit' ? 'Достигнут лимит реплик. Можно перейти к разбору.' : 'Посмотрите, что получилось и что можно попробовать иначе.'}</p></div></div>}
      </div>
      <div className="composer-area">
        {error && <ErrorNotice message={error} clear={() => setError('')} />}
        {confirmEnd && <div className="end-confirm"><div><strong>Завершить и получить разбор?</strong><p>Переписка сохранится. Если этапов мало, часть критериев останется без оценки.</p></div><div className="button-row"><button className="button secondary small" onClick={() => setConfirmEnd(false)}>Продолжить разговор</button><button className="button primary small" onClick={() => void finish()}>Получить разбор</button></div></div>}
        {confirmEnd ? null : finishing ? <div className="report-progress" role="status"><span className="typing-dots"><i /><i /><i /></span><div><strong>Сопоставляем реплики с критериями</strong><p>Один запрос для разбора. Стенограмма уже сохранена.</p></div></div> : session.status === 'completed' ? <button className="button primary full" onClick={() => void finish()}>Открыть разбор тренировки<Icon name="arrow" /></button> : <>
          {hint && <div className="hint"><strong>{observed.size === session.scenario.stages.length ? 'Все пункты обсуждены' : 'На что ещё обратить внимание'}</strong><p>{observed.size === session.scenario.stages.length ? 'Можно закончить разговор и перейти к разбору.' : stage.objective}</p></div>}
          <form className="composer" onSubmit={e => { e.preventDefault(); void send() }}><textarea ref={input} aria-label="Ваша реплика" placeholder="Напишите сообщение…" value={text} maxLength={2000} rows={2} onChange={e => setText(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send() } }} /><div className="composer-controls"><span className="numeric">{text.length} / 2000</span>{waiting ? <button type="button" className="button stop-button" onClick={() => void cancel()}><Icon name="stop" size={16} />Остановить ответ</button> : <button className="button primary" disabled={!text.trim() || (voiceConnected && (!voiceSend.current || (liveAvatar && !voiceReady)))}><Icon name="send" size={17} />Отправить</button>}</div></form>
          <div className="composer-help"><span>{voiceConnected ? 'Текст тоже можно отправить: он прервёт текущий ответ.' : 'Enter отправить · Shift + Enter новая строка'}</span>{session.mode === 'practice' && <button className="text-button" aria-expanded={hint} onClick={() => setHint(!hint)}>{hint ? 'Скрыть подсказку' : 'Нужна подсказка'}</button>}</div>
        </>}
      </div>
    </section>
  </div>
}
