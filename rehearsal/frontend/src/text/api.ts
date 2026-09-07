export async function api<T>(path: string, method = 'GET', body?: unknown, signal?: AbortSignal): Promise<T> {
  let response: Response
  try {
    response = await fetch(`/api/text${path}`, {
      method, headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body), signal,
    })
  } catch (error) {
    if (signal?.aborted) throw error
    throw new Error('Нет связи с сервером. Проверьте, запущен ли текстовый сервер на порту 8001. Данные на сервере сохраняются.')
  }
  const payload = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = payload?.detail
    throw new Error(typeof detail === 'string' ? detail : Array.isArray(detail)
      ? `Проверьте поля формы: ${detail.map((e: { loc: string[]; msg: string }) => `${e.loc.slice(1).join(' / ')}: ${e.msg}`).join('; ')}`
      : 'Сервер не выполнил запрос. Попробуйте обновить страницу.')
  }
  return payload as T
}
export const id = () => crypto.randomUUID()
export const date = (value: string) => new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }).format(new Date(value))
export const initials = (name: string) => name.split(' ').slice(0, 2).map(x => x[0]).join('')
export const plural = (n: number, words: [string, string, string]) => `${n} ${words[n % 100 >= 11 && n % 100 <= 14 ? 2 : n % 10 === 1 ? 0 : n % 10 >= 2 && n % 10 <= 4 ? 1 : 2]}`
