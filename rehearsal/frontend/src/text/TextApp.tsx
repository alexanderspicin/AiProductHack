import { useCallback, useEffect, useRef, useState } from 'react'
import { api, date, id, initials, plural } from './api'
import type { Bootstrap, Role, Scenario, Session, SessionCard } from './types'
import { Badge, Empty, ErrorNotice, Icon, Loading } from './ui'
import { ScenarioEditor } from './ScenarioEditor'
import { Conversation } from './Conversation'
import { ReportScreen } from './ReportScreen'
import { AdminScreen } from './AdminScreen'
import { ScenarioOverview } from './ScenarioOverview'
import { PresentationScreen } from './PresentationScreen'

const roleNames: Record<Role, string> = { participant: 'Участник', methodist: 'Методист', admin: 'Администратор' }
function readRole(): Role {
  const saved = localStorage.getItem('rehearsal-text-role')
  return saved === 'methodist' || saved === 'admin' ? saved : 'participant'
}
function routeNow() { return location.hash.slice(1) || '/library' }
export function go(path: string) { location.hash = path }

export function TextApp() {
  const [role, setRole] = useState<Role>(readRole)
  const [route, setRoute] = useState(routeNow)
  const [data, setData] = useState<Bootstrap | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [revision, setRevision] = useState(0)
  const [session, setSession] = useState<Session | null>(null)
  const [sessionError, setSessionError] = useState('')
  const [, page, itemId] = route.split('/')
  const reload = useCallback(() => setRevision(x => x + 1), [])
  useEffect(() => { const listener = () => setRoute(routeNow()); window.addEventListener('hashchange', listener); return () => window.removeEventListener('hashchange', listener) }, [])
  useEffect(() => {
    let active = true
    api<Bootstrap>(`/bootstrap?role=${role}`).then(value => { if (active) { setData(value); setError('') } }).catch(e => active && setError(e.message))
    return () => { active = false }
  }, [role, revision, page])
  useEffect(() => {
    if (!['session', 'report'].includes(page) || !itemId) { setSession(null); return }
    let active = true
    setSession(null); setSessionError('')
    api<Session>(`/sessions/${itemId}?staff=${role !== 'participant'}`).then(s => active && setSession(s)).catch(e => active && setSessionError(e.message))
    return () => { active = false }
  }, [page, itemId, role])
  useEffect(() => { if (!notice) return; const timer = window.setTimeout(() => setNotice(''), 4000); return () => clearTimeout(timer) }, [notice])
  const switchRole = (value: Role) => {
    if (!window.dispatchEvent(new Event('rehearsal:leave', { cancelable: true }))) return
    localStorage.setItem('rehearsal-text-role', value); setData(null); setRole(value)
    go(value === 'admin' ? '/settings' : '/library')
  }
  const selected = data?.scenarios.find(s => s.id === itemId)
  const nav: { path: string; label: string; icon: 'settings' | 'chart' | 'grid' }[] = role === 'admin'
    ? [{ path: '/settings', label: 'Настройки агента', icon: 'settings' as const }, { path: '/results', label: 'Все результаты', icon: 'chart' as const }]
    : [{ path: '/library', label: role === 'participant' ? 'Тренировки' : 'Сценарии', icon: 'grid' as const }, { path: '/results', label: role === 'participant' ? 'История тренировок' : 'Результаты участников', icon: 'chart' as const }]
  if (role !== 'participant') nav.push({ path: '/presentation', label: 'Персонаж тренировки', icon: 'settings' })
  const sectionTitle = page === 'settings' ? 'Управление агентом' : ['session', 'report'].includes(page) ? 'Тренировка' : page === 'results' ? 'Результаты' : role === 'participant' ? 'Пространство практики' : 'Кабинет методиста'
  return <div className={`workspace ${page === 'session' ? 'in-training' : ''}`}>
    <a className="skip-link" href="#main-content" onClick={event => { event.preventDefault(); document.getElementById('main-content')?.focus() }}>Перейти к содержимому</a>
    <aside className="sidebar">
      <a href={role === 'admin' ? '#/settings' : '#/library'} className="wordmark" aria-label="Репетиция, главная"><span className="brand-symbol"><i /><i /><i /></span>репетиция<span className="brand-period">.</span></a>
      <span className="workspace-label">Тренажёр диалогов</span>
      <nav aria-label="Основная навигация">{nav.map(n => <a key={n.path} href={`#${n.path}`} className={(route === n.path || (n.path === '/library' && ['scenario', 'edit', 'new'].includes(page))) ? 'selected' : ''} aria-current={route === n.path ? 'page' : undefined}><Icon name={n.icon} />{n.label}{n.path === '/library' && data && <span className="nav-count">{data.scenarios.filter(s => s.status !== 'archived').length}</span>}</a>)}</nav>
      <div className="sidebar-bottom">
        <div className="demo-label"><span className="small-dot" />Локальная демонстрация</div>
        <label className="role-label" htmlFor="workspace-role">Открыть как</label>
        <select id="workspace-role" value={role} onChange={e => switchRole(e.target.value as Role)}>{Object.entries(roleNames).map(([key, name]) => <option key={key} value={key}>{name}</option>)}</select>
        <p className="role-footnote">Роли для показа, без паролей.</p>
      </div>
    </aside>
    <div className="main-column">
      <header className="app-topbar"><span>{sectionTitle}</span><div className="topbar-right"><Badge>{data?.runtime.voice_mode === 'avatar' ? 'Голос и персонаж' : 'Текстовый режим'}</Badge><span className="profile-dot" aria-label={roleNames[role]}>{roleNames[role][0]}</span></div></header>
      <main id="main-content" tabIndex={-1} className={`page ${page === 'session' ? 'conversation-page' : ''}`}>
        {error && <ErrorNotice message={error} clear={() => setError('')} />}
        {!data ? error ? <button className="button" onClick={reload}>Повторить загрузку</button> : <Loading /> : <>
          {(page === 'library' || !page) && <Library data={data} role={role} reload={reload} notify={setNotice} />}
          {page === 'scenario' && (selected ? <Brief scenario={selected} data={data} onStart={s => { setSession(s); reload(); go(`/session/${s.id}`) }} /> : <Empty title="Сценарий недоступен">Возможно, методист снял его с публикации. Вернитесь к списку тренировок.</Empty>)}
          {(page === 'edit' || page === 'new') && (role !== 'participant' ? page === 'edit' && !selected ? <Empty title="Сценарий не найден" action={<a className="button secondary" href="#/library">К сценариям</a>}>Обновите список сценариев и выберите существующий.</Empty> : <ScenarioEditor key={itemId || 'new'} scenario={page === 'new' ? undefined : selected} onSaved={() => { reload(); setNotice('Сценарий сохранён'); go('/library') }} /> : <Empty title="Редактор в кабинете методиста">Переключите роль в меню слева.</Empty>)}
          {page === 'results' && <Results sessions={data.sessions} staff={role !== 'participant'} />}
          {page === 'presentation' && (role !== 'participant' && data.presentation ? <PresentationScreen data={data} reload={reload} notify={setNotice} /> : <Empty title="Выбор персонажа в кабинете методиста">Участник получает уже настроенную тренировку.</Empty>)}
          {page === 'settings' && (role === 'admin' && data.settings && data.budget ? <AdminScreen settings={data.settings} budget={data.budget} reload={reload} notify={setNotice} /> : <Empty title="Настройки в кабинете администратора">Участникам не нужно выбирать технический режим.</Empty>)}
          {['session', 'report'].includes(page) && (sessionError ? <ErrorNotice message={sessionError} /> : !session ? <Loading /> : page === 'session' ? <Conversation key={session.id} initial={session} onFinish={s => { setSession(s); reload(); go(`/report/${s.id}`) }} /> : <ReportScreen key={session.id} initial={session} staff={role !== 'participant'} onChange={reload} />)}
          {!['library', 'scenario', 'edit', 'new', 'results', 'settings', 'presentation', 'session', 'report'].includes(page) && <Empty title="Страница не найдена" action={<a className="button primary" href="#/library">К тренировкам</a>}>Выберите раздел в меню.</Empty>}
        </>}
      </main>
    </div>
    {notice && <div className="toast" role="status"><Icon name="check" />{notice}</div>}
  </div>
}

function Library({ data, role, reload, notify }: { data: Bootstrap; role: Role; reload: () => void; notify: (value: string) => void }) {
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState('Все')
  const [showArchived, setShowArchived] = useState(false)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const staff = role !== 'participant'
  const categories = ['Все', ...new Set(data.scenarios.filter(s => s.status !== 'archived').map(s => s.category).filter(Boolean))]
  const scenarios = data.scenarios.filter(s => (showArchived || s.status !== 'archived') && (category === 'Все' || s.category === category) && `${s.title} ${s.description}`.toLowerCase().includes(query.toLowerCase()))
  const copy = async (scenario: Scenario) => {
    setBusy(scenario.id); setError('')
    const { id: _id, revision: _r, updated_at: _u, ...draft } = scenario
    try { await api<Scenario>('/scenarios', 'POST', { ...draft, title: `${draft.title.slice(0, 100)} · копия`, status: 'draft' }); reload(); notify('Копия создана как черновик. Откройте её в списке.') }
    catch (e) { setError((e as Error).message) } finally { setBusy('') }
  }
  return <>
    <div className="page-heading"><div><h1>{staff ? 'Сценарии тренировок' : 'Мои тренировки'}</h1><p>{staff ? 'Задайте ситуацию, характер собеседника и критерии хорошего разговора.' : 'Безопасное место, чтобы попробовать, ошибиться и найти свои слова.'}</p></div>{staff && <a className="button primary" href="#/new"><Icon name="plus" />Создать сценарий</a>}</div>
    {!staff && <section className="welcome-strip"><div><span className="welcome-tag"><Icon name="chat" size={17} />Практика сложных разговоров</span><h2>Подготовьтесь к разговору,<br />который имеет значение.</h2><p>Выберите ситуацию. Собеседник ответит на ваши слова, а в конце вы получите разбор по критериям.</p></div><div className="welcome-detail"><span className="conversation-glyph" aria-hidden="true"><Icon name="chat" size={52} /></span><span>В своём темпе</span><small>{data.runtime.voice_mode === 'avatar' ? 'Текст, микрофон и персонаж' : 'Текстовый диалог'}</small></div></section>}
    {data.runtime.is_demo && <div className="notice warning"><Icon name="info" /><span>Включён демонстрационный режим с заготовленными репликами. Реальную модель подключает администратор.</span></div>}
    {error && <ErrorNotice message={error} clear={() => setError('')} />}
    <div className="library-layout"><section>
      <div className="section-row"><h2>{staff ? 'Библиотека сценариев' : 'Выберите ситуацию'} <span className="muted-count">{scenarios.length}</span></h2><label className="search-field"><Icon name="search" size={18} /><input aria-label="Поиск сценариев" placeholder="Найти сценарий" value={query} onChange={e => setQuery(e.target.value)} /></label></div>
      <div className="filter-row" aria-label="Категории">{categories.map(c => <button key={c} className={`filter ${category === c ? 'active' : ''}`} aria-pressed={category === c} onClick={() => setCategory(c)}>{c}</button>)}{staff && <label className="archive-toggle"><input type="checkbox" checked={showArchived} onChange={e => setShowArchived(e.target.checked)} />Архив</label>}</div>
      <div className="scenario-list">{scenarios.map((s, i) => <article className="scenario-row" key={s.id}>
        <div className={`scenario-monogram color-${i % 3}`} aria-hidden="true">{initials(s.npc_name)}</div>
        <div className="scenario-row-main"><div className="scenario-meta"><span>{s.category}</span>{staff && <Badge tone={s.status === 'published' ? 'green' : ''}>{({ published: 'Опубликован', draft: 'Черновик', archived: 'В архиве' })[s.status]}</Badge>}</div><a className="scenario-title" href={`#/${staff ? 'edit' : 'scenario'}/${s.id}`}>{s.title}</a><p>{s.description}</p><div className="scenario-facts"><span><Icon name="clock" size={15} />{s.duration_minutes} мин</span><span>{plural(s.stages.length, ['этап', 'этапа', 'этапов'])}</span><span>{plural(s.criteria.length, ['критерий', 'критерия', 'критериев'])}</span></div></div>
        <div className="scenario-actions">{staff ? <><a className="icon-button" aria-label={`Редактировать: ${s.title}`} href={`#/edit/${s.id}`}><Icon name="edit" /></a><button className="icon-button" disabled={busy === s.id} onClick={() => void copy(s)} aria-label={`Создать копию: ${s.title}`}><Icon name="copy" /></button></> : <a className="icon-button forward" aria-label={`Открыть тренировку: ${s.title}`} href={`#/scenario/${s.id}`}><Icon name="arrow" /></a>}</div>
      </article>)}</div>
      {!scenarios.length && <Empty title="Сценариев не найдено">Измените поиск или выберите другую категорию.</Empty>}
    </section>
    <aside className="guide-column"><h3>{staff ? 'Сценарий, который работает' : 'Как это устроено'}</h3><ol className="guide-steps">{(staff ? [['Ситуация', 'Одна понятная задача участника и конкретный контекст.'], ['Ход разговора', 'Для каждого этапа задайте цель и первую реплику.'], ['Оценка', 'Опишите наблюдаемое поведение, которое считаете успешным.']] : [['Изучите задачу', 'Узнайте свою роль и цель разговора.'], ['Поговорите', 'Отвечайте своими словами, как в работе.'], ['Разберите результат', 'Посмотрите сильные стороны и выберите, что улучшить.']]).map(([title, copy]) => <li key={title}><strong>{title}</strong><p>{copy}</p></li>)}</ol><div className="quiet-note"><Icon name="info" size={19} /><p>{staff ? 'Изменения сценария применяются к новым тренировкам. Старые результаты сохраняют исходные критерии.' : 'Это учебная ситуация. Не вводите реальные персональные данные, пароли и рабочие секреты.'}</p></div></aside>
    </div>
  </>
}

function Brief({ scenario: s, data, onStart }: { scenario: Scenario; data: Bootstrap; onStart: (s: Session) => void }) {
  const [name, setName] = useState(localStorage.getItem('rehearsal-text-name') || '')
  const [consent, setConsent] = useState(false)
  const [voiceConsent, setVoiceConsent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const requestId = useRef(id())
  const start = async () => {
    if (busy) return
    setBusy(true); setError('')
    try { localStorage.setItem('rehearsal-text-name', name.trim()); onStart(await api<Session>('/sessions', 'POST', { scenario_id: s.id, participant: name.trim() || 'Участник', consent, voice_consent: voiceConsent, request_id: requestId.current })) }
    catch (e) { setError((e as Error).message); setBusy(false) }
  }
  return <>
    <a className="back-link" href="#/library"><Icon name="back" size={17} />Все тренировки</a>
    <div className="brief-layout"><ScenarioOverview scenario={s} voice={data.runtime.voice_mode === 'avatar'} /><aside className="start-panel"><div className="person-monogram">{initials(s.npc_name)}</div><span className="subtle-label">Ваш собеседник</span><h2>{s.npc_name}</h2><p>{s.npc_role}</p><div className="divider" /><form onSubmit={e => { e.preventDefault(); void start() }}>
      <label className="field">Как к вам обращаться<input value={name} maxLength={80} onChange={e => { setName(e.target.value); requestId.current = id() }} placeholder="Имя или учебный псевдоним" /><small>Можно оставить пустым.</small></label>
      {data.runtime.external_processing && <label className="consent"><input type="checkbox" required checked={consent} onChange={e => setConsent(e.target.checked)} /><span>Разрешаю отправить вымышленные реплики и сценарий в OpenAI для диалога и разбора. Без личных и рабочих секретов.</span></label>}
      {data.runtime.voice_mode === 'avatar' && <label className="consent"><input type="checkbox" required checked={voiceConsent} onChange={e => setVoiceConsent(e.target.checked)} /><span>Разрешаю передавать ответы персонажа в Cartesia или Inworld для голоса и Tavus или Anam для видео. Микрофон распознаётся на локальном сервере, камера не используется. Внешним видеосервисам передаётся только синтезированный звук.</span></label>}
      {error && <ErrorNotice message={error} />}
      <button className="button primary full" disabled={busy || (data.runtime.external_processing && !consent) || (data.runtime.voice_mode === 'avatar' && !voiceConsent)}>{busy ? 'Начинаем…' : 'Начать тренировку'}<Icon name="arrow" /></button>
    </form><p className="panel-footnote">Разговор можно завершить в любой момент. Переписка сохранится.</p></aside></div>
  </>
}

export function Results({ sessions, staff }: { sessions: SessionCard[]; staff: boolean }) {
  const [filter, setFilter] = useState('all')
  const [query, setQuery] = useState('')
  const shown = sessions.filter(s => (filter === 'all' || (filter === 'review' ? s.status === 'completed' && !s.reviewed : s.status === filter)) && `${s.title} ${s.participant}`.toLowerCase().includes(query.toLowerCase()))
  return <><div className="page-heading"><div><h1>{staff ? 'Результаты участников' : 'История тренировок'}</h1><p>{staff ? 'Проверьте выводы агента и оставьте участнику обратную связь.' : 'Вернитесь к разговору или посмотрите, над чем поработать дальше.'}</p></div></div>
    <div className="notice compact"><Icon name="info" size={18} /><span>Локальная демонстрация: здесь видны тренировки всех участников этого стенда.</span></div>
    <div className="section-row"><div className="filter-row">{[['all', 'Все'], ['active', 'В процессе'], ['completed', 'Завершённые'], ...(staff ? [['review', 'Ждут проверки']] : [])].map(([value, title]) => <button className={`filter ${filter === value ? 'active' : ''}`} key={value} aria-pressed={filter === value} onClick={() => setFilter(value)}>{title}</button>)}</div><label className="search-field"><Icon name="search" size={18} /><input aria-label="Поиск результатов" placeholder="Поиск по имени и сценарию" value={query} onChange={e => setQuery(e.target.value)} /></label></div>
    {shown.length ? <div className="table-scroll"><table>
      <thead><tr><th>Тренировка / участник</th><th>Дата</th><th>Состояние</th><th>Оценка</th><th><span className="sr-only">Действие</span></th></tr></thead>
      <tbody>{shown.map(s => <tr key={s.id}>
        <td><strong>{s.title}</strong><small>{s.participant}{s.is_demo ? ' · демо' : ''}</small></td>
        <td>{date(s.created_at)}</td>
        <td><Badge tone={s.status === 'active' ? '' : s.reviewed ? 'green' : 'amber'}>{s.status === 'active' ? 'В процессе' : s.reviewed ? 'Проверено' : 'Ждёт проверки'}</Badge></td>
        <td className="numeric score-cell">{s.score === null ? 'Нет оценки' : <>{s.score} / 100<small>Охват {s.covered} из {s.total}</small></>}</td>
        <td><a className="button small secondary" href={`#/${s.status === 'active' ? 'session' : 'report'}/${s.id}`}>{s.status === 'active' ? 'Продолжить' : 'Открыть разбор'}<Icon name="arrow" size={16} /></a></td>
      </tr>)}</tbody>
    </table></div> : <Empty title={sessions.length ? 'Нет подходящих тренировок' : 'Здесь появится первый разговор'} action={<a className="button primary" href="#/library">Выбрать тренировку</a>}>{sessions.length ? 'Измените фильтр или поисковый запрос.' : 'После тренировки сохранятся стенограмма, оценка по критериям и комментарий методиста.'}</Empty>}
  </>
}
