import { useEffect, type ReactNode } from 'react'

export function useUnsavedChanges(dirty: boolean) {
  useEffect(() => {
    const confirmLeave = (event: Event) => {
      if (dirty && !window.confirm('Есть несохранённые изменения. Выйти без сохранения?')) event.preventDefault()
    }
    const beforeUnload = (event: BeforeUnloadEvent) => { if (dirty) event.preventDefault() }
    const click = (event: MouseEvent) => {
      const link = (event.target as Element).closest?.('a[href]')
      if (link && link.getAttribute('href')?.startsWith('#/') && link.getAttribute('href') !== location.hash) confirmLeave(event)
    }
    document.addEventListener('click', click, true)
    window.addEventListener('rehearsal:leave', confirmLeave)
    window.addEventListener('beforeunload', beforeUnload)
    return () => { document.removeEventListener('click', click, true); window.removeEventListener('rehearsal:leave', confirmLeave); window.removeEventListener('beforeunload', beforeUnload) }
  }, [dirty])
}

const paths = {
  grid: 'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
  chat: 'M21 11.5a8.5 8.5 0 0 1-8.5 8.5H4l-2 2v-9.5A8.5 8.5 0 1 1 21 11.5Z M7 9h10 M7 13h6',
  chart: 'M4 3v17h17 M9 15v-4 M14 15V7 M19 15V4',
  book: 'M4 3h12a3 3 0 0 1 3 3v15H6a3 3 0 0 1-3-3V6a3 3 0 0 1 3-3 M3 17h16 M8 7h6 M8 11h5',
  settings: 'M4 7h16 M4 17h16 M8 4v6 M16 14v6',
  arrow: 'M5 12h14 M13 6l6 6-6 6',
  back: 'M19 12H5 M11 6l-6 6 6 6',
  plus: 'M12 5v14 M5 12h14',
  check: 'M5 12l4 4L19 6',
  close: 'M6 6l12 12 M18 6L6 18',
  search: 'M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14 M15 15l6 6',
  clock: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18 M12 7v5l3 2',
  copy: 'M9 9h12v12H9z M15 5V3H3v12h2',
  edit: 'M4 16l-1 5 5-1L21 7l-4-4L4 16Z M14 6l4 4',
  download: 'M12 3v12 M7 10l5 5 5-5 M4 16v5h16v-5',
  stop: 'M6 6h12v12H6z',
  play: 'm9 5 11 7-11 7V5Z',
  phoneEnd: 'M3 14c5-5 13-5 18 0v4h-5v-4 M8 14v4H3',
  send: 'm21 3-6 18-4-8-8-4 18-6Z M11 13 21 3',
  info: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18 M12 11v6 M12 7v.5',
  up: 'm6 15 6-6 6 6',
  down: 'm6 9 6 6 6-6',
  archive: 'M3 3h18v5H3z M5 8v13h14V8 M9 12h6',
  refresh: 'M20 7a9 9 0 1 0 1 9 M20 2v6h-6',
  mic: 'M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3Z M5 11v1a7 7 0 0 0 14 0v-1 M12 19v3 M8 22h8',
  micOff: 'M4 4l16 16 M9 9v3a3 3 0 0 0 5 2 M15 10V6a3 3 0 0 0-5.6-1.5 M5 11v1a7 7 0 0 0 11 5.7 M19 11v1c0 1.1-.3 2.1-.7 3 M12 19v3 M8 22h8',
  volume: 'M5 10v4h4l5 4V6l-5 4H5 M17 9a4 4 0 0 1 0 6 M19 6a8 8 0 0 1 0 12',
} as const
export function Icon({ name, size = 20 }: { name: keyof typeof paths; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]} /></svg>
}
export function Badge({ children, tone = '' }: { children: ReactNode; tone?: string }) {
  return <span className={`badge ${tone}`}>{children}</span>
}
export function ErrorNotice({ message, clear }: { message: string; clear?: () => void }) {
  return <div className="notice error" role="alert"><Icon name="info" /><span>{message}</span>{clear && <button className="icon-button" onClick={clear} aria-label="Закрыть сообщение"><Icon name="close" /></button>}</div>
}
export function Loading() {
  return <div className="loading-shell" aria-label="Загрузка" role="status"><div className="skeleton heading" /><div className="skeleton block" /><div className="skeleton block short" /><span className="sr-only">Загружаем данные</span></div>
}
export function Empty({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return <div className="empty-state"><span className="empty-icon"><Icon name="book" size={28} /></span><h2>{title}</h2><p>{children}</p>{action}</div>
}
