import { useEffect, useState } from 'react'
import { api } from './api'
import type { Bootstrap, Presentation } from './types'
import { Badge, ErrorNotice, Icon, useUnsavedChanges } from './ui'

export function PresentationScreen({ data, reload, notify }: { data: Bootstrap; reload: () => void; notify: (message: string) => void }) {
  const saved = data.presentation!
  const [draft, setDraft] = useState(saved)
  const [busy, setBusy] = useState(false), [error, setError] = useState('')
  useEffect(() => setDraft(saved), [saved.revision])
  useUnsavedChanges(JSON.stringify(saved) !== JSON.stringify(draft))
  const save = async () => {
    setBusy(true); setError('')
    try { setDraft(await api<Presentation>('/presentation', 'PUT', draft)); reload(); notify('Персонаж выбран. Настройка действует для новых тренировок.') }
    catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  return <>
    <div className="page-heading"><div><h1>Персонаж тренировки</h1><p>Выберите внешность, имя и голос. Роль, характер и факты задаются в сценарии.</p></div><Badge>Кабинет методиста</Badge></div>
    <form className="presentation-form" onSubmit={e => { e.preventDefault(); void save() }}>
      {error && <ErrorNotice message={error} clear={() => setError('')} />}
      {data.runtime.is_demo && <div className="notice warning">Сейчас включены заготовленные ответы. Для живого голоса администратор должен выбрать OpenAI.</div>}
      <section className="settings-section"><h2>Как участник разговаривает</h2>
        <div className="mode-options">{[['avatar', 'Голос и живое видео'], ['text', 'Только переписка']].map(([value, title]) => <label key={value} className={`mode-option ${draft.voice_mode === value ? 'selected' : ''}`}><input type="radio" name="presentation-mode" checked={draft.voice_mode === value} onChange={() => setDraft(d => ({ ...d, voice_mode: value as Presentation['voice_mode'] }))} /><strong>{title}</strong></label>)}</div>
      </section>
      <fieldset className="character-options" disabled={busy || draft.voice_mode === 'text'}><legend>Основные персонажи</legend>
        {data.avatar_profiles?.filter(p => p.id !== 'legacy_3d').map(p => <label key={p.id} className={`character-option ${draft.avatar_profile === p.id ? 'selected' : ''}`}>
          <input type="radio" name="avatar-profile" value={p.id} checked={draft.avatar_profile === p.id} onChange={() => setDraft(d => ({ ...d, avatar_profile: p.id }))} />
          <span className="character-copy"><strong>{p.title}</strong><span>{p.description}</span><small>{data.avatar_status?.[p.id]?.detail || 'Подключение проверяется при запуске'}</small></span>
          <Badge tone={data.avatar_status?.[p.id]?.available ? 'green' : 'amber'}>{data.avatar_status?.[p.id]?.available ? 'Подключён' : 'Нужна настройка'}</Badge>
        </label>)}
      </fieldset>
      <p className="section-description">При запуске новой тренировки модель согласует имя и род начальной реплики с персонажем. Этот текст появится в чате и прозвучит в озвучке. Исходный сценарий и прошлые разговоры сохраняются. В деморежиме используются нейтральные заготовки.</p>
      <section className="settings-section"><h2>Если видео задерживается</h2>
        <label className="consent"><input type="checkbox" checked={draft.allow_audio_fallback} onChange={e => setDraft(d => ({ ...d, allow_audio_fallback: e.target.checked }))} /><span>Разрешить разговор без видео с тем же голосом. Участник сможет включить его отдельной кнопкой, история сохранится.</span></label>
        <p className="section-description">Замена не происходит незаметно посреди реплики. Переписка доступна всегда.</p>
        {draft.avatar_profile === 'legacy_3d' && <div className="notice compact warning">Сейчас выбран прежний 3D-персонаж. Выберите Даниила или Татьяну выше, чтобы перейти на новую версию.</div>}
      </section>
      <div className="notice compact"><Icon name="info" size={18} /><span>Настройки применяются к новым тренировкам. Уже начатые разговоры сохраняют прежнего персонажа. Видео использует минуты Tavus или Anam; подключение запускается только кнопкой «Начать разговор».</span></div>
      <div className="settings-save"><button type="button" className="button secondary" disabled={busy} onClick={() => setDraft(saved)}>Отменить изменения</button><button className="button primary" disabled={busy}>{busy ? 'Сохраняем…' : 'Сохранить персонажа'}<Icon name="check" size={17} /></button></div>
    </form>
  </>
}
