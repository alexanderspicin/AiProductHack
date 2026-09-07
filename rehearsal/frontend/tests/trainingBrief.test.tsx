import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, test } from 'vitest'
import { TrainingBrief } from '../src/text/TrainingBrief'
import type { Scenario } from '../src/text/types'

const description = 'Сотрудник должен понять причину сомнений клиента, связать решение с его задачами и договориться о следующем шаге.'
const scenario: Scenario = {
  id: 'sales', revision: 1, title: 'Сложный клиент', category: 'Продажи', description,
  situation: 'Вы встретились обсудить корпоративное обучение.', employee_role: 'Менеджер',
  npc_name: 'Даниил', npc_role: 'Клиент', duration_minutes: 7, status: 'published', stages: [], criteria: [],
}
afterEach(cleanup)

test('brief addresses the participant in one coherent instruction without changing the source', () => {
  render(<TrainingBrief scenario={scenario} />)
  expect(document.querySelector('.brief-task')?.textContent).toBe('Ваша задача: понять причину сомнений клиента, связать решение с его задачами и договориться о следующем шаге.')
  expect(document.body.textContent).not.toContain('Сотрудник должен')
  expect(scenario.description).toBe(description)
})

test('custom instructions remain unchanged and the fallback uses the same wording', () => {
  const custom = 'Обсудите причины. Сотрудник должен получить обратную связь.'
  const view = render(<TrainingBrief scenario={{ ...scenario, description: custom }} />)
  expect(document.querySelector('.brief-task')?.textContent).toBe(`Ваша задача: ${custom}`)
  view.rerender(<TrainingBrief scenario={{ ...scenario, situation: '' }} />)
  expect(screen.getByText('понять причину сомнений клиента, связать решение с его задачами и договориться о следующем шаге.')).toBeTruthy()
})
