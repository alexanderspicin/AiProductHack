import { useEffect, useState } from 'react'
import type { Bootstrap } from './types'
import { Badge, Icon } from './ui'
import './usage.css'

const number = (value: number) => value.toLocaleString('ru-RU')
const dollars = (value: number | null) => value === null ? 'Нет данных' : new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'USD', minimumFractionDigits: 4, maximumFractionDigits: 6 }).format(value)
const stateNames: Record<string, string> = { completed: 'Готово', failed: 'Ошибка', cancelled: 'Отменён', pending: 'Нет результата', untracked: 'Старая запись' }

export function ApiUsagePanel({ budget, reload }: { budget: NonNullable<Bootstrap['budget']>; reload: () => void }) {
  const usage = budget.usage
  const [rate, setRate] = useState(() => { try { return localStorage.getItem('rehearsal-usd-rub') || '' } catch { return '' } })
  const conversion = Number(rate.replace(',', '.'))
  const validRate = Number.isFinite(conversion) && conversion > 0 && conversion <= 100000
  useEffect(() => {
    const timer = window.setInterval(() => { if (!document.hidden) reload() }, 10000)
    return () => window.clearInterval(timer)
  }, [reload])
  const setConversion = (value: string) => {
    setRate(value)
    try { localStorage.setItem('rehearsal-usd-rub', value) } catch { /* Optional display preference. */ }
  }
  const priced = usage?.estimated_cost_usd ?? null
  return <aside className="connection-panel usage-panel" aria-label="Расходы текстового API">
    <div className="section-row"><h3>Текстовый API</h3><Badge tone={budget.available ? 'green' : 'amber'}>{budget.available ? 'Включён' : 'Выключен'}</Badge></div>
    <p>Без лимита запросов в приложении. Ограничения и баланс OpenAI продолжают действовать.</p>
    <dl className="connection-facts">
      <div><dt>Ключ на сервере</dt><dd>{budget.key_configured ? 'Задан' : 'Нет ключа'}</dd></div>
      <div><dt>Попыток всего</dt><dd>{number(budget.used_requests)}</dd></div>
      <div><dt>Токенов учтено</dt><dd>{usage?.measured_requests ? number(usage.total_tokens) : 'Нет данных'}</dd></div>
      {usage && usage.measured_requests > 0 && <>
        <div><dt>Входные</dt><dd>{number(usage.input_tokens)}</dd></div>
        <div><dt>Из них из кэша</dt><dd>{number(usage.cached_tokens)}</dd></div>
        <div><dt>Из них запись в кэш</dt><dd>{number(usage.cache_write_tokens)}</dd></div>
        <div><dt>Выходные</dt><dd>{number(usage.output_tokens)}</dd></div>
        {usage.reasoning_tokens > 0 && <div><dt>Из них рассуждение</dt><dd>{number(usage.reasoning_tokens)}</dd></div>}
      </>}
      <div className="remaining"><dt>Расчётная стоимость</dt><dd>{dollars(priced)}</dd></div>
      {validRate && priced !== null && <div><dt>По вашему курсу</dt><dd>≈ {new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB', minimumFractionDigits: 2, maximumFractionDigits: 4 }).format(priced * conversion)}</dd></div>}
    </dl>
    <label className="field usage-rate">Курс для оценки, ₽ за $<input inputMode="decimal" value={rate} maxLength={12} placeholder="Укажите свой курс оплаты" onChange={e => setConversion(e.target.value)} aria-invalid={rate !== '' && !validRate} aria-describedby="usage-rate-hint" /></label>
    <p className="panel-footnote" id="usage-rate-hint">Курс задаётся вручную, сохраняется в этом браузере. Комиссии и налоги не включены.</p>
    <button className="button secondary full" onClick={reload}><Icon name="refresh" size={17} />Обновить статистику</button>
    {usage ? <>
      <p className="panel-footnote">Токены получены от API для {number(usage.measured_requests)} из {number(budget.used_requests)} попыток. Сумма рассчитана для {number(usage.priced_requests)}. Статистика этого сервера, не всего аккаунта. Обновляется каждые 10 секунд бесплатно.</p>
      {usage.unpriced_requests > 0 && <div className="quiet-note"><Icon name="info" size={18} /><p>У {number(usage.unpriced_requests)} попыток стоимость неизвестна. Старые записи, ошибки и прерывания могут не содержать данных. Они не включены в сумму и не считаются бесплатными.</p></div>}
      <details className="usage-details"><summary>Последние запросы и тарифы</summary>
        <ul className="usage-requests">{usage.recent.map((item, i) => <li key={`${item.created_at}-${i}`}>
          <div><strong>{item.operation === 'text_report' ? 'Разбор тренировки' : item.operation === 'text_opening' ? 'Подготовка первой реплики' : 'Ответ собеседника'}</strong><span>{stateNames[item.state] || item.state}</span></div>
          <small>{new Date(`${item.created_at.replace(' ', 'T')}Z`).toLocaleString('ru-RU')} · {item.model || 'Модель не записана'}</small>
          <span>{item.total_tokens === null ? 'Токены неизвестны' : `${number(item.total_tokens)} токенов`} · {dollars(item.estimated_cost_usd)}</span>
        </li>)}</ul>
        <p className="panel-footnote">Тарифы проверены {usage.price_version}. Учитываем кэш и запись в кэш; рассуждение уже входит в выходные токены. Неизвестный тариф не подставляем.</p>
        <div className="usage-links"><a href="https://developers.openai.com/api/docs/models/gpt-5.6-luna" target="_blank" rel="noreferrer">Тариф Luna</a><a href="https://developers.openai.com/api/docs/models/gpt-4.1-mini" target="_blank" rel="noreferrer">Тариф GPT-4.1 mini</a><a href="https://platform.openai.com/usage" target="_blank" rel="noreferrer">Сверить с OpenAI</a></div>
      </details>
    </> : <p className="panel-footnote">Статистика токенов пока недоступна. Обновите сервер.</p>}
  </aside>
}
