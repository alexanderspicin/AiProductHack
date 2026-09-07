import { useEffect } from 'react'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import type { Session } from '../src/text/types'

const call = vi.hoisted(() => ({ send: vi.fn(async () => {}), stop: vi.fn(async () => {}) }))
vi.mock('../src/voice/VoiceTools', () => ({ VoiceTools: (props: any) => {
  useEffect(() => { props.stopRef.current = call.stop; return () => { props.stopRef.current = null } }, [])
  return <section>
    <button disabled={props.disabled || props.startDisabled} onClick={() => props.onConnection(true)}>Начать диалог</button>
    <button onClick={() => { props.sendRef.current = call.send; props.onReady() }}>Голос готов</button>
    <button onClick={props.onEnd}>Завершить</button>
  </section>
} }))
import { Conversation } from '../src/text/Conversation'
import { reportMarkdown } from '../src/text/ReportScreen'

const fixture = (): Session => ({
  id: 'call-test', participant: 'Тест', stage_index: 0, status: 'active', turns: [], report: null,
  report_status: 'none', report_error: '', completion_reason: '', review_note: '', reviewed: false,
  voice_mode: 'avatar', avatar_profile: 'legacy_3d', allow_audio_fallback: true,
  created_at: '2026-09-06T10:00:00Z', mode: 'practice', is_demo: false, max_turns: 12, opening_message: 'Я отправила отчёт.',
  scenario: { id: 'custom', revision: 1, title: 'Тренировка', category: 'Тест', description: 'Договоритесь о следующем шаге.', employee_role: 'Менеджер', npc_name: 'Татьяна', npc_role: 'Коллега', duration_minutes: 5, status: 'published', stages: [{ id: 'one', title: 'Выяснить причину', objective: 'Задайте уточняющий вопрос' }], criteria: [] },
})
beforeEach(() => { call.send.mockClear(); call.stop.mockReset(); call.stop.mockResolvedValue(); vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(fixture()), { status: 200 }))) })
afterEach(async () => { cleanup(); await act(async () => {}); vi.unstubAllGlobals() })

test('text becomes available at bot-ready, without waiting for session polling or starting a second pipeline', async () => {
  render(<Conversation initial={fixture()} onFinish={vi.fn()} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Начать диалог' }))
  fireEvent.change(screen.getByRole('textbox', { name: 'Ваша реплика' }), { target: { value: 'Что помешало закончить вовремя?' } })
  expect((screen.getByRole('button', { name: 'Отправить' }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: 'Голос готов' }))
  expect((screen.getByRole('button', { name: 'Отправить' }) as HTMLButtonElement).disabled).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: 'Отправить' }))
  await waitFor(() => expect(call.send).toHaveBeenCalledWith('Что помешало закончить вовремя?'))
  expect(fetch).not.toHaveBeenCalled()
})

test('finish waits for voice cleanup before requesting the report; dismissing confirmation preserves the draft', async () => {
  let stopped!: () => void
  call.stop.mockImplementation(() => new Promise<void>(resolve => { stopped = resolve }))
  const finished = vi.fn()
  render(<Conversation initial={fixture()} onFinish={finished} />)
  await screen.findByRole('button', { name: 'Начать диалог' })
  fireEvent.change(screen.getByRole('textbox', { name: 'Ваша реплика' }), { target: { value: 'Черновик' } })
  fireEvent.click(screen.getByRole('button', { name: 'Завершить' }))
  fireEvent.keyDown(document, { key: 'Escape' })
  expect((screen.getByRole('textbox', { name: 'Ваша реплика' }) as HTMLTextAreaElement).value).toBe('Черновик')
  fireEvent.click(screen.getByRole('button', { name: 'Завершить' }))
  fireEvent.click(screen.getByRole('button', { name: 'Получить разбор' }))
  expect(call.stop).toHaveBeenCalledOnce()
  expect(fetch).not.toHaveBeenCalled()
  await act(async () => { stopped() })
  expect(fetch).toHaveBeenCalledWith('/api/text/sessions/call-test/end', expect.objectContaining({ method: 'POST' }))
  expect(finished).toHaveBeenCalledOnce()
})

test('voice cannot start on top of an unfinished text request', async () => {
  const session = fixture()
  session.turns = [{ id: 'pending', request_id: 'pending', user_text: 'Вопрос', reply: '', status: 'pending', stage_index: 0, elapsed_ms: null, created_at: session.created_at }]
  render(<Conversation initial={session} onFinish={vi.fn()} />)
  expect((await screen.findByRole('button', { name: 'Начать диалог' }) as HTMLButtonElement).disabled).toBe(true)
  expect(screen.getByRole('button', { name: 'Остановить ответ' })).toBeTruthy()
})

test('ordered plan stays visible and a future observed goal does not hide an earlier gap', async () => {
  const s = fixture()
  s.progress_mode = 'flexible'
  s.scenario.stages.push({ id: 'two', title: 'Договориться', objective: 'Назвать действие и срок.' })
  s.stage_progress = [{ stage_id: 'two', quote: 'Завтра проверим', turn_id: 't0' }]
  render(<Conversation initial={s} onFinish={vi.fn()} />)
  const plan = screen.getByRole('navigation', { name: 'Краткий план разговора' })
  expect(within(plan).getAllByRole('button').map(b => b.getAttribute('aria-label'))).toEqual([
    '1. Выяснить причину. Открыть задание', '2. Договориться. Обсуждено. Открыть задание',
  ])
  expect(screen.queryByRole('complementary', { name: 'Задание тренировки' })).toBeNull()
  fireEvent.click(within(plan).getAllByRole('button')[1])
  expect(screen.getByText('Назвать действие и срок.')).toBeTruthy()
  expect(screen.getByText(/не означает оценку навыка/)).toBeTruthy()
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(plan).toBeTruthy()
  expect(reportMarkdown(s)).toContain('Выяснить причину: нет подтверждения')
  expect(reportMarkdown(s)).toContain('Цитата: «Завтра проверим»')
  await act(async () => {})
})

test('new text session opens at public brief, without hidden facts or an assessment hint', async () => {
  const s = fixture()
  s.voice_mode = 'text'; s.mode = 'assessment'
  s.scenario.situation = 'Отчёт снова задержался. Вы встретились обсудить причины.'
  s.scenario.context = 'Секретные факты персонажа'
  render(<Conversation initial={s} onFinish={vi.fn()} />)
  expect(screen.getByRole('region', { name: 'Ситуация перед разговором' })).toBeTruthy()
  expect(screen.getByText(s.scenario.situation)).toBeTruthy()
  expect(document.body.textContent).not.toContain(s.scenario.context)
  expect(screen.queryByRole('button', { name: 'Нужна подсказка' })).toBeNull()
  expect(screen.getByRole('textbox', { name: 'Ваша реплика' })).toBeTruthy()
  expect(fetch).not.toHaveBeenCalled()
  await act(async () => {})
})
