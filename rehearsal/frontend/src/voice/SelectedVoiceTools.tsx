import { useEffect, useRef, useState, type MutableRefObject, type ReactNode } from 'react'
import { PipecatClient } from '@pipecat-ai/client-js'
import { WebSocketTransport } from '@pipecat-ai/websocket-transport'
import { api } from '../text/api'
import type { AvatarProfile } from '../text/types'
import { ErrorNotice, Icon } from '../text/ui'
import { CallMicrophoneManager } from './CallMicrophoneManager'
import { AudioClockPlayer } from './AudioClockPlayer'
import { AudioRelay, isAvatarAudioEvent, type AudioSink } from './AudioRelay'
import { RemoteAvatar, bounded, type PreparedAvatar } from './RemoteAvatar'

type Props = { sessionId: string; name: string; profile: AvatarProfile; allowAudioFallback: boolean; disabled: boolean; startDisabled?: boolean
  intro?: ReactNode
  onConnection: (connected: boolean) => void; onReady?: () => void; onEnd?: () => void
  stopRef?: MutableRefObject<(() => Promise<void>) | null>; sendRef: MutableRefObject<((text: string) => Promise<void>) | null> }
type Resources = { requestId: string; bot: PipecatClient | null; remote: RemoteAvatar | null; relay: AudioRelay | null
  player: AudioClockPlayer | null; media?: CallMicrophoneManager; prepared?: PreparedAvatar; timer?: ReturnType<typeof setTimeout> }

export function SelectedVoiceTools({ sessionId, name, profile, intro, allowAudioFallback, disabled, startDisabled = false, onConnection, onReady, onEnd, sendRef, stopRef }: Props) {
  const video = useRef<HTMLVideoElement>(null)
  const options = useRef<HTMLDetailsElement>(null)
  const active = useRef<Resources | null>(null), closing = useRef<Promise<void> | null>(null)
  const cleanupRequest = useRef<string | null>(null)
  const [state, setState] = useState('off'), [error, setError] = useState('')
  const [muted, setMuted] = useState(false), [audioOnly, setAudioOnly] = useState(false)
  const [micBusy, setMicBusy] = useState(false), [micNotice, setMicNotice] = useState('')
  const [hasConnected, setHasConnected] = useState(false)
  const [caption, setCaption] = useState(''), [subtitle, setSubtitle] = useState('')
  const [latency, setLatency] = useState<number | null>(null), [stopLatency, setStopLatency] = useState<number | null>(null)
  const [remaining, setRemaining] = useState<number | null>(null)
  const handoff = useRef<number | null>(null), userSpeaking = useRef(false)
  const callback = useRef(onConnection); callback.current = onConnection
  const ready = useRef(false)
  const alive = useRef(true)
  const metric = (kind: string, ms: number) => active.current?.bot?.sendClientMessage('playback_metric', { kind, ms: Math.round(ms) })

  const disconnect = (): Promise<void> => {
    if (closing.current) return closing.current
    const r = active.current || (cleanupRequest.current ? { requestId: cleanupRequest.current, bot: null, remote: null, relay: null, player: null } as Resources : null)
    active.current = null; ready.current = false; sendRef.current = null
    if (!r) { callback.current(false); return Promise.resolve() }
    cleanupRequest.current = r.requestId
    r.relay?.suspend(); r.player?.interrupt(); clearTimeout(r.timer)
    if (alive.current) { setState('disconnecting'); setRemaining(null) }
    const work = async () => {
      const results = await Promise.allSettled([
        bounded(r.bot?.disconnect() || Promise.resolve(), 4000, 'Голос ещё отключается'),
        r.remote?.close(), r.player?.close(),
        api(`/sessions/${sessionId}/voice/stop`, 'POST', { request_id: r.requestId }),
      ])
      const serverResult = results[3]
      if (serverResult.status === 'fulfilled') cleanupRequest.current = null
      if (alive.current && serverResult.status === 'rejected') setError('Не удалось подтвердить остановку на сервере. Нажмите «Повторить отключение».')
      callback.current(false)
      if (alive.current) { setState(cleanupRequest.current ? 'cleanup_failed' : 'off'); setSubtitle('') }
    }
    closing.current = work().finally(() => { closing.current = null })
    return closing.current
  }
  useEffect(() => {
    alive.current = true
    if (stopRef) stopRef.current = disconnect
    const unload = () => {
      active.current?.relay?.suspend()
      if (active.current) void fetch(`/api/text/sessions/${sessionId}/voice/stop`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ request_id: active.current.requestId }), keepalive: true })
    }
    window.addEventListener('pagehide', unload)
    return () => { alive.current = false; if (stopRef) stopRef.current = null; window.removeEventListener('pagehide', unload); void disconnect() }
  }, [sessionId])
  useEffect(() => { if (disabled) void disconnect() }, [disabled])
  useEffect(() => {
    const outside = (event: PointerEvent) => {
      if (options.current && !options.current.contains(event.target as Node)) options.current.open = false
    }
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && options.current?.open) {
        options.current.open = false
        options.current.querySelector('summary')?.focus()
      }
    }
    document.addEventListener('pointerdown', outside)
    document.addEventListener('keydown', escape)
    return () => { document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', escape) }
  }, [])
  useEffect(() => {
    if (remaining === null) return
    const timer = setInterval(() => setRemaining(n => n === null ? null : Math.max(0, n - 1)), 1000)
    return () => clearInterval(timer)
  }, [remaining === null])

  const connect = async (withoutVideo = false, microphone = true) => {
    if (active.current || closing.current || cleanupRequest.current || disabled || startDisabled) return
    const r: Resources = { requestId: crypto.randomUUID(), bot: null, remote: null, relay: null, player: null }
    active.current = r; ready.current = false; userSpeaking.current = false; handoff.current = null
    setLatency(null); setStopLatency(null)
    const current = () => active.current === r && alive.current
    const fail = (e: Error) => { if (current()) { setError(e.message); void disconnect() } }
    const speaking = (value: boolean) => {
      if (!current() || userSpeaking.current) return
      setState(value ? 'bot' : 'listening')
      if (value && handoff.current !== null) {
        const ms = performance.now() - handoff.current; handoff.current = null; setLatency(ms); metric('handoff_to_audio', ms)
      }
    }
    setError(''); setMicNotice(''); setCaption(''); setState('connecting'); setAudioOnly(withoutVideo); setMuted(!microphone); setSubtitle('')
    callback.current(true)
    try {
      let sink: AudioSink
      if (withoutVideo) {
        let number = 0
        const player = new AudioClockPlayer(() => {})
        r.player = player; await player.unlock()
        sink = { start: async () => { player.event({ type: 'playback_start', utterance_id: ++number }) },
          chunk: audio => { const bytes = Uint8Array.from(atob(audio), c => c.charCodeAt(0)); player.buffer(bytes.buffer); speaking(true) },
          end: () => {}, interrupt: () => { player.interrupt(); speaking(false) } }
      } else {
        r.remote = new RemoteAvatar(video.current!, speaking, fail)
        await r.remote.unlock(); sink = r.remote
      }
      r.relay = new AudioRelay(sink, fail)
      r.media = new CallMicrophoneManager({
          // PCM arrives through tagged server events; ignore paced binary duplicate.
          buffer: data => data instanceof Int16Array ? data : new Int16Array(data),
          interrupt: () => r.relay?.suspend(),
        })
      const bot = new PipecatClient({ enableMic: microphone, enableCam: false,
        transport: new WebSocketTransport({ mediaManager: r.media }),
        callbacks: {
          onBotReady: () => { if (current()) {
            ready.current = true; setState('listening'); setHasConnected(true)
            sendRef.current = async text => {
              r.relay?.suspend(); setSubtitle(''); setState('thinking'); handoff.current = performance.now()
              await bot.sendText(text, { run_immediately: true, audio_response: true })
            }
            onReady?.()
          } },
          onDisconnected: () => { if (current()) void disconnect() },
          onUserStartedSpeaking: () => { if (current()) {
            const began = performance.now(); userSpeaking.current = true; r.relay?.userSpeaking(true)
            const ms = performance.now() - began; setStopLatency(ms); metric('vad_event_to_mute', ms)
            setSubtitle(''); setState('user'); handoff.current = null
          } },
          onUserStoppedSpeaking: () => { if (current()) { userSpeaking.current = false; r.relay?.userSpeaking(false); handoff.current = performance.now(); setState('thinking') } },
          onBotStoppedSpeaking: () => { if (current() && withoutVideo && !userSpeaking.current) setState('listening') },
          onUserTranscript: data => { if (current()) setCaption(data.text) },
          onBotTtsText: data => { if (current() && !userSpeaking.current) setSubtitle(s => `${s} ${data.text}`.trim().slice(-350)) },
          onServerMessage: message => { if (current() && isAvatarAudioEvent(message)) r.relay?.event(message) },
          onError: () => fail(new Error('Ошибка голосового сервера. Проверьте подключение или продолжите текстом.')),
        },
      })
      r.bot = bot
      // Ask for the microphone before reserving provider minutes.
      try { await bot.initDevices() }
      catch (error) {
        if (!current()) return
        const kind = (error as Error).name
        if (!microphone || !['NotAllowedError', 'NotFoundError', 'NotReadableError', 'DevicesError'].includes(kind)) throw error
        await r.media.enableMic(false)
        setMuted(true); setMicNotice('Микрофон недоступен. Пишите в чат: собеседник ответит голосом. Включить микрофон можно позже.')
        await bot.initDevices()
      }
      if (!current()) return
      r.prepared = await api<PreparedAvatar>(`/sessions/${sessionId}/voice/prepare`, 'POST', { request_id: r.requestId, audio_only: withoutVideo })
      if (!current()) { await api(`/sessions/${sessionId}/voice/stop`, 'POST', { request_id: r.requestId }); return }
      const began = performance.now()
      if (r.remote) await bounded(r.remote.connect(r.prepared), 30000, 'Видео слишком долго подключается. Можно продолжить без видео.')
      if (!current()) return
      const connectMs = performance.now() - began
      const url = new URL(r.prepared.path, location.origin); url.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
      await bounded(bot.connect({ wsUrl: url.toString() }), 40000, 'Голосовой сервер не готов. Проверьте модели распознавания.')
      if (!current()) return
      metric('video_connect', connectMs)
      const seconds = Math.max(0, r.prepared.max_seconds - Math.ceil((performance.now() - began) / 1000))
      setRemaining(seconds)
      r.timer = setTimeout(() => { if (current()) { setError('Пробная голосовая сессия завершена. Переписка сохранена, можно продолжить текстом.'); void disconnect() } }, seconds * 1000)
    } catch (e) {
      if (current()) { setError((e as Error).message); await disconnect() }
    }
  }
  const interrupt = () => {
    const r = active.current
    r?.relay?.suspend(); r?.bot?.sendClientMessage('interrupt')
    setState('listening'); setSubtitle(''); handoff.current = null
  }
  const toggleMic = async () => {
    if (micBusy || (state !== 'off' && !ready.current)) return
    const enabled = muted
    if (!active.current?.media) { setMuted(!enabled); return }
    const r = active.current
    setMicBusy(true)
    try {
      await r.media!.enableMic(enabled)
      if (active.current !== r || !alive.current) return
      setMuted(!enabled); setMicNotice('')
      if (!enabled && userSpeaking.current) {
        userSpeaking.current = false; r.relay?.userSpeaking(false); setState('listening')
      }
    } catch {
      if (active.current === r && alive.current) { setMuted(true); setMicNotice('Не удалось включить микрофон. Проверьте разрешение браузера. Чат продолжает работать.') }
    } finally { if (alive.current) setMicBusy(false) }
  }
  const connecting = state === 'connecting' || state === 'disconnecting'
  const stateLabel = { off: hasConnected ? 'Диалог на паузе' : 'Готовы к разговору?', connecting: 'Подключаем собеседника…', disconnecting: 'Отключаемся…', cleanup_failed: 'Нужно завершить отключение', listening: muted ? 'Микрофон выключен. Пишите в чат.' : 'Ваш ход. Можно говорить или писать.', user: 'Слушаю вас', thinking: 'Собеседник готовит ответ…', bot: 'Собеседник говорит' }[state]
  return <section className="selected-voice" aria-label="Живой собеседник">
    <div className={`human-video ${audioOnly ? 'audio-only' : ''}`}>
      <video ref={video} autoPlay playsInline aria-label={`Видео собеседника ${name}`} />
      {(state === 'off' || connecting || state === 'cleanup_failed' || audioOnly) && <div className={`human-video-cover ${state === 'off' && !hasConnected && !disabled && intro ? 'has-brief' : ''}`}>{state === 'off' && !hasConnected && !disabled && intro ? intro : <><span className="call-person-monogram" aria-hidden="true">{name.slice(0, 1)}</span><strong>{name}</strong><span>{disabled ? 'Разговор завершён' : audioOnly ? 'Вы слышите собеседника без видео' : connecting ? stateLabel : 'Собеседник начнёт первым. Дальше говорите или пишите в чат.'}</span></>}</div>}
      <span className="ai-disclosure">ИИ-персонаж</span>
      {remaining !== null && <span className="voice-time numeric" aria-label="Осталось секунд голосовой сессии">{Math.floor(remaining / 60)}:{String(remaining % 60).padStart(2, '0')}</span>}
      {subtitle && <p className="call-subtitle" aria-live="off">{subtitle}</p>}
      <span className="call-nameplate">{name}</span>
    </div>
    <div className="call-controls">
      {(error || micNotice) && <div className="call-notices">{error && <ErrorNotice message={error} clear={() => setError('')} />}{micNotice && <p role="status">{micNotice}</p>}</div>}
      <div className="voice-state" role="status"><span className={`voice-dot ${state === 'user' || state === 'bot' ? 'active' : ''}`} />{disabled ? 'Диалог завершён' : stateLabel}</div>
      <div className="call-toolbar">
        <button className={`button secondary mic-toggle ${muted ? 'is-muted' : ''}`} title={muted ? 'Включить микрофон' : 'Выключить микрофон'} aria-pressed={!muted} disabled={disabled || micBusy || (state !== 'off' && !ready.current)} onClick={() => void toggleMic()}><Icon name={muted ? 'micOff' : 'mic'} size={20} /><span>{muted ? 'Включить микрофон' : 'Выключить микрофон'}</span></button>
        {state === 'off' ? <button className="button primary call-start" disabled={disabled || startDisabled} onClick={() => void connect(audioOnly, !muted)}><Icon name="play" size={19} />{hasConnected ? 'Продолжить диалог' : 'Начать диалог'}</button>
          : connecting || state === 'cleanup_failed' ? <button className="button secondary" disabled={state === 'disconnecting'} onClick={() => void disconnect()}>{state === 'cleanup_failed' ? 'Повторить отключение' : state === 'disconnecting' ? 'Отключаемся…' : 'Отменить подключение'}</button>
          : <button className="button secondary" disabled={!ready.current || !['bot', 'thinking'].includes(state)} onClick={interrupt}><Icon name="stop" size={18} />Перебить</button>}
        {onEnd && <button className="button call-end" aria-label="Завершить" title="Завершить и получить разбор" onClick={onEnd} disabled={disabled}><Icon name="phoneEnd" size={20} /><span>Завершить</span></button>}
        <details ref={options} className="call-options"><summary aria-label="Параметры разговора"><Icon name="settings" size={20} /><span>Ещё</span></summary><div className="call-options-panel">
          <strong>Параметры разговора</strong><p>Камера не включается. Лучше использовать наушники. Можно перебивать собеседника голосом или новым сообщением.</p>
          {state === 'off' && allowAudioFallback && <label className="checkbox-row"><input type="checkbox" checked={audioOnly} onChange={e => setAudioOnly(e.target.checked)} />Без видео, только голос собеседника</label>}
          {ready.current && <button className="button secondary full" onClick={() => void disconnect()}>Приостановить диалог</button>}
          {ready.current && !audioOnly && allowAudioFallback && <button className="button secondary full" onClick={() => { const microphone = !muted; void disconnect().then(() => connect(true, microphone)) }}>Продолжить без видео</button>}
          <details className="voice-diagnostics"><summary>Технические данные</summary><p>{profile === 'tavus_sergei' ? 'Cartesia Sergei · Tavus Daniel' : 'Cartesia Tatiana · Anam Cara'}</p><p>До звука: {latency === null ? 'ещё не измерено' : `${Math.round(latency)} мс`}. От VAD-события до заглушения: {stopLatency === null ? 'ещё не измерено' : `${Math.round(stopLatency)} мс`}. Сеть и обнаружение речи не включены.</p>{caption && <p>Распознано: {caption}</p>}</details>
        </div></details>
      </div>
    </div>
  </section>
}
