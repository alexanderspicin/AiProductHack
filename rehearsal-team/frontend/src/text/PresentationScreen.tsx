import { useEffect, useState } from 'react'
import { api } from './api'
import type { Bootstrap, Presentation } from './types'
import { Badge, ErrorNotice } from './ui'

export function PresentationScreen({ data, reload, notify }: { data: Bootstrap; reload: () => void; notify: (message: string) => void }) {
  const saved = data.presentation!, [draft, setDraft] = useState(saved), [error, setError] = useState(''), [busy, setBusy] = useState(false)
  useEffect(() => setDraft(saved), [saved.revision])
  return <><div className="page-heading"><div><h1>Формат тренировки</h1><p>Версия на исходном бэкенде команды, как в презентации.</p></div><Badge>Кабинет методиста</Badge></div>
    <form onSubmit={async e => { e.preventDefault(); setBusy(true); setError(''); try { await api('/presentation', 'PUT', { ...draft, avatar_profile: 'legacy_3d' }); reload(); notify('Формат сохранён для новых тренировок.') } catch(e) { setError((e as Error).message) } finally { setBusy(false) } }}>
      {error && <ErrorNotice message={error} clear={() => setError('')} />}
      <section className="settings-section"><h2>Как участник разговаривает</h2><div className="mode-options">{[['avatar', 'Голос, текст и 3D-персонаж'], ['text', 'Только переписка']].map(([value, label]) => <label className={`mode-option ${draft.voice_mode === value ? 'selected' : ''}`} key={value}><input type="radio" checked={draft.voice_mode === value} name="format" onChange={() => setDraft({ ...draft, voice_mode: value as Presentation['voice_mode'] })} /><strong>{label}</strong></label>)}</div></section>
      <section className="settings-section"><h2>3D-персонаж команды</h2><p>Распознавание, начало и конец реплики обрабатываются локально: faster-whisper, Silero VAD и Smart Turn v3. Inworld озвучивает ответы; Three.js анимирует модель по словам и таймингам.</p><p>Роль, имя, характер и первая реплика задаются в сценарии. Используется одна модель персонажа; ключ и голос Inworld настраивает администратор в серверном .env.local.</p><p>{data.avatar_status?.legacy_3d?.detail}</p></section>
      <div className="notice compact">OpenAI и Inworld требуют интернета. Видеогенераторы Tavus, Anam и LiveAvatar эта версия не вызывает. API-версия сохранена отдельно в репозитории.</div>
      <div className="settings-save"><button type="button" className="button secondary" onClick={() => setDraft(saved)}>Отменить изменения</button><button className="button primary" disabled={busy}>{busy ? 'Сохраняем…' : 'Сохранить формат'}</button></div>
    </form></>
}
