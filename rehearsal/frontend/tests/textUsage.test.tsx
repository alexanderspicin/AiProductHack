import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { ApiUsagePanel } from '../src/text/ApiUsagePanel'
import type { Bootstrap } from '../src/text/types'

const memory = new Map<string, string>()
Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: {
  getItem: (key: string) => memory.get(key) ?? null,
  setItem: (key: string, value: string) => memory.set(key, String(value)),
  clear: () => memory.clear(),
} })

const budget = (): NonNullable<Bootstrap['budget']> => ({ available: true, enabled: true, key_configured: true, unlimited: true,
  max_requests: null, remaining_requests: null, used_requests: 3,
  usage: { input_tokens: 1000, output_tokens: 200, total_tokens: 1200, cached_tokens: 400, cache_write_tokens: 100, reasoning_tokens: 50,
    measured_requests: 1, unmeasured_requests: 2, priced_requests: 1, unpriced_requests: 2, estimated_cost_usd: .000373,
    price_version: '2026-09-04', price_sources: [], first_measured_at: null, recent: [] },
})
afterEach(() => { cleanup(); localStorage.clear(); vi.useRealTimers() })

test('shows tokens, estimated cost, unknown attempts and no remaining cap', () => {
  render(<ApiUsagePanel budget={budget()} reload={vi.fn()} />)
  expect(screen.getByText(/Без лимита запросов/)).toBeTruthy()
  expect(screen.getByText('Токенов учтено')).toBeTruthy()
  expect(screen.getByText(/У 2 попыток стоимость неизвестна/)).toBeTruthy()
  expect(screen.queryByText('Осталось запросов')).toBeNull()
  fireEvent.change(screen.getByLabelText('Курс для оценки, ₽ за $'), { target: { value: '90,5' } })
  expect(screen.getByText('По вашему курсу')).toBeTruthy()
  expect(localStorage.getItem('rehearsal-usd-rub')).toBe('90,5')
})

test('missing cost never displays zero dollars', () => {
  const data = budget(); data.usage!.estimated_cost_usd = null; data.usage!.measured_requests = 0
  render(<ApiUsagePanel budget={data} reload={vi.fn()} />)
  expect(screen.getAllByText('Нет данных').length).toBe(2)
  expect(screen.queryByText(/0,0000/)).toBeNull()
})

test('initial greeting preparation is identified separately in usage', () => {
  const data = budget()
  data.usage!.recent = [{ operation: 'text_opening', state: 'completed', created_at: '2026-09-06 18:00:00', model: 'gpt-5.6-luna', total_tokens: 170, estimated_cost_usd: .0001 }]
  render(<ApiUsagePanel budget={data} reload={vi.fn()} />)
  expect(screen.getByText('Подготовка первой реплики')).toBeTruthy()
  expect(screen.queryByText('Ответ собеседника')).toBeNull()
})

test('auto refresh is read-only and stops after unmount', () => {
  vi.useFakeTimers()
  const reload = vi.fn()
  const view = render(<ApiUsagePanel budget={budget()} reload={reload} />)
  vi.advanceTimersByTime(10000)
  expect(reload).toHaveBeenCalledTimes(1)
  view.unmount()
  vi.advanceTimersByTime(10000)
  expect(reload).toHaveBeenCalledTimes(1)
})
