import type { Scenario } from './types'

export interface ScenarioIssue { tab: number; label: string; field: string }
export const editorTabs = ['Ситуация', 'Персонаж', 'Этапы', 'Критерии']

export function scenarioIssues(s: Scenario): ScenarioIssue[] {
  const issues: ScenarioIssue[] = []
  const check = (value: string | undefined, min: number, tab: number, label: string, field: string) => {
    if ((value?.trim().length || 0) < min) issues.push({ tab, label, field })
  }
  check(s.title, 2, 0, 'Название сценария', 'title')
  check(s.category, 2, 0, 'Категория', 'category')
  check(s.description, 5, 0, 'Задача участника', 'description')
  check(s.employee_role, 2, 0, 'Роль участника', 'employee_role')
  if (!Number.isInteger(s.duration_minutes) || s.duration_minutes < 2 || s.duration_minutes > 30)
    issues.push({ tab: 0, label: 'Время: целое число от 2 до 30 минут', field: 'duration_minutes' })
  check(s.npc_name, 2, 1, 'Имя собеседника', 'npc_name')
  check(s.npc_role, 2, 1, 'Роль собеседника', 'npc_role')
  check(s.manner, 5, 1, 'Характер и манера общения', 'manner')
  check(s.context, 5, 1, 'Факты ситуации', 'context')
  s.stages.forEach((stage, i) => {
    check(stage.title, 2, 2, `Этап ${i + 1}: название`, `stage-${stage.id}-title`)
    check(stage.objective, 5, 2, `Этап ${i + 1}: цель`, `stage-${stage.id}-objective`)
    check(stage.opening_line, 2, 2, `Этап ${i + 1}: первая реплика`, `stage-${stage.id}-opening_line`)
  })
  s.criteria.forEach((criterion, i) => {
    check(criterion.title, 2, 3, `Критерий ${i + 1}: название`, `criterion-${criterion.id}-title`)
    check(criterion.description, 5, 3, `Критерий ${i + 1}: наблюдаемое поведение`, `criterion-${criterion.id}-description`)
  })
  return issues
}
