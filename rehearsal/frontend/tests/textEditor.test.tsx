import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { ScenarioEditor } from '../src/text/ScenarioEditor'
import { ReportScreen } from '../src/text/ReportScreen'
import { scenarioIssues } from '../src/text/scenarioReadiness'
import type { Scenario, Session } from '../src/text/types'

const scenario = (): Scenario => ({ id: 'example', revision: 1, status: 'draft', title: 'Черновик', category: 'Тест', description: '', employee_role: '', npc_name: '', npc_role: '', manner: '', context: '', boundaries: '', duration_minutes: 7, stages: [{ id: 'step', title: '', objective: '', opening_line: '' }], criteria: [{ id: 'criterion', title: '', description: '', weight: 1 }] })
const response = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

test('new draft saves with a title only and no generation call', async () => {
  const fetcher = vi.fn(async () => response(scenario()))
  vi.stubGlobal('fetch', fetcher)
  const onSaved = vi.fn()
  render(<ScenarioEditor onSaved={onSaved} />)
  fireEvent.change(screen.getByLabelText('Название сценария'), { target: { value: 'Первая идея' } })
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить черновик' }))
  await waitFor(() => expect(onSaved).toHaveBeenCalledOnce())
  const [url, options] = fetcher.mock.calls[0] as unknown as [string, RequestInit]
  expect(url).toBe('/api/text/scenarios')
  expect(JSON.parse(options.body as string)).toMatchObject({ status: 'draft', title: 'Первая идея', description: '' })
  expect(fetcher).toHaveBeenCalledOnce()
})

test('publication lists missing fields, opens their section, does not save', async () => {
  const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher)
  render(<ScenarioEditor scenario={scenario()} onSaved={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'Опубликовать' }))
  expect(screen.getByRole('alert').textContent).toContain('не готов к публикации')
  expect(screen.getByRole('status').textContent).toBe('Готово 0 из 4 разделов')
  fireEvent.click(screen.getByRole('button', { name: 'Этап 1: первая реплика' }))
  await waitFor(() => expect(screen.getByRole('tab', { name: 'Этапы' }).getAttribute('aria-selected')).toBe('true'))
  expect(screen.getByLabelText('Первая реплика собеседника')).toBeTruthy()
  expect(fetcher).not.toHaveBeenCalled()
})

test('preview retains unsaved changes and excludes private context without API calls', () => {
  const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher)
  const s = scenario(); s.context = 'PRIVATE-CONTEXT'; s.manner = 'PRIVATE-MANNER'; s.boundaries = 'PRIVATE-BOUNDARIES'
  s.stages[0].opening_line = 'Добрый день, обсудим сроки?'
  render(<ScenarioEditor scenario={s} onSaved={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('Название сценария'), { target: { value: 'Несохранённая правка' } })
  fireEvent.change(screen.getByRole('textbox', { name: /Ситуация перед разговором/ }), { target: { value: 'Открытая вводная для участника' } })
  fireEvent.click(screen.getByRole('button', { name: 'Предпросмотр участника' }))
  expect(screen.getByRole('heading', { name: 'Несохранённая правка' })).toBeTruthy()
  expect(screen.getByText('Добрый день, обсудим сроки?')).toBeTruthy()
  expect(screen.getByText('Открытая вводная для участника')).toBeTruthy()
  expect(document.body.textContent).not.toContain('PRIVATE-')
  expect(screen.queryByRole('button', { name: 'Начать тренировку' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Вернуться в редактор' }))
  expect((screen.getByLabelText('Название сценария') as HTMLInputElement).value).toBe('Несохранённая правка')
  expect(fetcher).not.toHaveBeenCalled()
})

test('server revision conflict keeps draft and allows manual recovery', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => response({ detail: 'Сценарий изменён в другом окне. Обновите страницу.' }, 409)))
  const onSaved = vi.fn()
  render(<ScenarioEditor scenario={scenario()} onSaved={onSaved} />)
  fireEvent.change(screen.getByLabelText('Название сценария'), { target: { value: 'Моя правка' } })
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить черновик' }))
  await screen.findByRole('alert')
  expect((screen.getByLabelText('Название сценария') as HTMLInputElement).value).toBe('Моя правка')
  expect(onSaved).not.toHaveBeenCalled()
})

test('readiness matches minimum lengths and checks duration', () => {
  const s = scenario()
  expect(scenarioIssues(s).map(i => i.field)).toContain('stage-step-opening_line')
  s.duration_minutes = 0
  expect(scenarioIssues(s).map(i => i.field)).toContain('duration_minutes')
  s.duration_minutes = 7
  s.description = s.employee_role = s.npc_name = s.npc_role = s.manner = s.context = 'Заполнено'
  s.stages[0] = { id: 'step', title: 'Начало', objective: 'Обсудить вопрос', opening_line: 'Добрый день' }
  s.criteria[0] = { id: 'criterion', title: 'Контакт', description: 'Задаёт вопросы', weight: 1 }
  expect(scenarioIssues(s)).toEqual([])
})

test('unsaved review blocks leaving; saving removes the guard', async () => {
  const s: Session = { id: 'session-test', scenario: scenario(), participant: 'Тест', stage_index: 0, status: 'completed', turns: [], report: null, report_status: 'none', report_error: '', completion_reason: '', review_note: '', reviewed: false, created_at: '2026-09-04T08:00:00Z', mode: 'practice', is_demo: true, max_turns: 12, opening_message: 'Привет' }
  vi.stubGlobal('fetch', vi.fn(async () => response({ ...s, review_note: 'Проверено', reviewed: true })))
  const confirm = vi.fn(() => false)
  vi.stubGlobal('confirm', confirm)
  render(<ReportScreen initial={s} staff onChange={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('Комментарий методиста'), { target: { value: '  Проверено  ' } })
  fireEvent.click(screen.getByLabelText('Разбор проверен по стенограмме'))
  expect(window.dispatchEvent(new Event('rehearsal:leave', { cancelable: true }))).toBe(false)
  expect(confirm).toHaveBeenCalledOnce()
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить комментарий' }))
  await screen.findByText('Комментарий сохранён')
  expect(window.dispatchEvent(new Event('rehearsal:leave', { cancelable: true }))).toBe(true)
  expect(confirm).toHaveBeenCalledOnce()
})
