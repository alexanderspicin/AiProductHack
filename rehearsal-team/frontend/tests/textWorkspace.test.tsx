import { StrictMode } from 'react'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { Conversation } from '../src/text/Conversation'
import { reportMarkdown } from '../src/text/ReportScreen'
import type { Session } from '../src/text/types'

const fixture = (): Session => ({
  id: 'session-test', participant: 'Тест', stage_index: 0, status: 'active', turns: [], report: null,
  report_status: 'none', report_error: '', completion_reason: '', review_note: '', reviewed: false,
  created_at: '2026-09-03T10:00:00Z', mode: 'practice', is_demo: false, max_turns: 12, opening_message: 'Что вы предлагаете?',
  scenario: { id: 'custom', revision: 1, title: 'Тренировка', category: 'Тест', description: 'Договоритесь о следующем шаге.', employee_role: 'Менеджер', npc_name: 'Анна Тест', npc_role: 'Клиент', duration_minutes: 5, status: 'published', stages: [{ id: 'one', title: 'Выяснить причину', objective: 'Задайте уточняющий вопрос' }], criteria: [{ id: 'one', title: 'Вопросы', description: 'Уточняет потребность', weight: 1 }] },
})
const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

test('stop drops a late response and keeps a new draft', async () => {
  const s = fixture()
  let resolveLate!: (value: Response) => void
  let requestId = ''
  const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    if (url.endsWith('/turns')) {
      requestId = JSON.parse(options?.body as string).request_id
      return new Promise<Response>(resolve => { resolveLate = resolve })
    }
    if (url.endsWith('/cancel')) return response({ ...s, turns: [{ id: requestId, request_id: requestId, user_text: 'Первый вопрос', reply: '', stage_index: 0, status: 'cancelled', created_at: s.created_at, elapsed_ms: null }] })
    return response(s)
  })
  vi.stubGlobal('fetch', fetcher)
  render(<Conversation initial={s} onFinish={vi.fn()} />)
  fireEvent.change(screen.getByRole('textbox', { name: 'Ваша реплика' }), { target: { value: 'Первый вопрос' } })
  fireEvent.click(screen.getByRole('button', { name: 'Отправить' }))
  await waitFor(() => expect(fetcher).toHaveBeenCalled())
  fireEvent.change(screen.getByRole('textbox', { name: 'Ваша реплика' }), { target: { value: 'Новый вопрос' } })
  fireEvent.click(screen.getByRole('button', { name: 'Остановить ответ' }))
  await waitFor(() => expect(screen.getByText('Ответ остановлен. Реплика не вошла в оценку.')).toBeTruthy())
  await act(async () => resolveLate(response({ ...s, turns: [{ id: requestId, request_id: requestId, user_text: 'Первый вопрос', reply: 'УСТАРЕВШИЙ ОТВЕТ', stage_index: 0, status: 'committed' }] })))
  expect(screen.queryByText('УСТАРЕВШИЙ ОТВЕТ')).toBeNull()
  expect((screen.getByRole('textbox', { name: 'Ваша реплика' }) as HTMLTextAreaElement).value).toBe('Новый вопрос')
})

test('StrictMode restoration does not cancel an in-flight generation', async () => {
  const s = fixture()
  s.turns = [{ id: 'old', request_id: 'pending-old', user_text: 'Вопрос', reply: '', stage_index: 0, status: 'pending', created_at: s.created_at, elapsed_ms: null }]
  const fetcher = vi.fn(async () => response(s))
  vi.stubGlobal('fetch', fetcher)
  const result = render(<StrictMode><Conversation initial={s} onFinish={vi.fn()} /></StrictMode>)
  await act(async () => { await Promise.resolve() })
  expect(fetcher.mock.calls.length).toBe(0)
  result.unmount()
  await act(async () => { await Promise.resolve() })
  expect(fetcher.mock.calls.length).toBe(1)
})

test('API failure is visible, with no automatic retry', async () => {
  const s = fixture()
  const fetcher = vi.fn(async (url: string) => url.endsWith('/turns') ? response({ detail: 'Лимит исчерпан' }, 503) : response(s))
  vi.stubGlobal('fetch', fetcher)
  render(<Conversation initial={s} onFinish={vi.fn()} />)
  fireEvent.change(screen.getByRole('textbox', { name: 'Ваша реплика' }), { target: { value: 'Проверка' } })
  fireEvent.click(screen.getByRole('button', { name: 'Отправить' }))
  await screen.findByRole('alert')
  expect(screen.getByRole('alert').textContent).toContain('Лимит исчерпан')
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/turns')).length).toBe(1)
})

test('assessment has no hint and zero remains a real score in export', () => {
  const s = fixture(); s.mode = 'assessment'
  render(<Conversation initial={s} onFinish={vi.fn()} />)
  expect(screen.queryByRole('button', { name: 'Нужна подсказка' })).toBeNull()
  s.report = { summary: 'Результат', warning: 'Проверка методиста', overall_score: 0, covered: 1, total: 1, source: 'llm', strengths: [], next_steps: [], criteria: [], created_at: s.created_at }
  expect(reportMarkdown(s)).toContain('Оценка: 0 / 100')
  expect(reportMarkdown(s)).not.toContain('context')
})
