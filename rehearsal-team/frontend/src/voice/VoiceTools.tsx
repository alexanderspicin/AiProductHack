import { useEffect, useRef, useState, type MutableRefObject, type ReactNode } from 'react'
import { PipecatClient } from '@pipecat-ai/client-js'
import { WebSocketTransport } from '@pipecat-ai/websocket-transport'
import { AvatarStage } from '../avatar/AvatarStage'
import { isAvatarEvent } from '../protocol/avatarProtocol'
import { AvatarStream } from './AvatarStream'
import { api } from '../text/api'
import { Icon } from '../text/ui'

type Props = { sessionId: string; name: string; disabled: boolean; startDisabled?: boolean; intro?: ReactNode
  onConnection: (connected: boolean) => void; onReady: () => void; onEnd: () => void
  sendRef: MutableRefObject<((text: string) => Promise<void>) | null>; stopRef: MutableRefObject<(() => Promise<void>) | null> }

export function VoiceTools({ sessionId, name, disabled, startDisabled, intro, onConnection, onReady, onEnd, sendRef, stopRef }: Props) {
  const [stream] = useState(() => new AvatarStream())
  const client = useRef<PipecatClient | null>(null), generation = useRef(0)
  const stopping = useRef<Promise<void> | null>(null)
  const [state, setState] = useState('off'), [error, setError] = useState(''), [muted, setMuted] = useState(false)
  const [caption, setCaption] = useState('')
  const [preview, setPreview] = useState(false)
  const captionsBlocked = useRef(true)
  const callbacks = useRef({ onConnection, onReady }); callbacks.current = { onConnection, onReady }
  const stop = () => {
    if (stopping.current) return stopping.current
    const version = ++generation.current
    const bot = client.current; client.current = null
    sendRef.current = null; captionsBlocked.current = true; stream.reset(); setCaption(''); setState('stopping')
    callbacks.current.onConnection(true)
    const done = (async () => {
      try { await bot?.disconnect() } catch { /* Server shutdown is confirmed below. */ }
      await api(`/sessions/${sessionId}/voice/stop`, 'POST')
      if (generation.current === version) { setState('off'); callbacks.current.onConnection(false) }
    })().catch(e => { if (generation.current === version) setState('cleanup_failed'); throw e }).finally(() => { stopping.current = null })
    stopping.current = done
    return done
  }
  useEffect(() => { stopRef.current = stop; return () => {
    generation.current++; const bot = client.current; client.current = null
    sendRef.current = null; stopRef.current = null; stream.reset()
    void bot?.disconnect().catch(() => {})
  } }, [sessionId, stream, sendRef, stopRef])
  useEffect(() => { if (disabled && client.current) void stop().catch(e => setError(e.message)) }, [disabled])

  const connect = async () => {
    if (client.current || stopping.current) return
    const version = ++generation.current, current = () => version === generation.current
    setState('connecting'); setError(''); setMuted(false); setCaption(''); callbacks.current.onConnection(true)
    try {
      const prepared = await api<{ path: string }>(`/sessions/${sessionId}/voice/prepare`, 'POST')
      if (!current()) return
      // Same official transport/player as the original teammate frontend.
      const bot = new PipecatClient({ transport: new WebSocketTransport(), enableMic: true, enableCam: false, callbacks: {
        onBotReady: () => { if (current()) {
          setState('listening'); callbacks.current.onReady()
          sendRef.current = async text => { captionsBlocked.current = true; stream.interrupt(); setCaption(''); await bot.sendText(text, { run_immediately: true, audio_response: true }) }
        } },
        onDisconnected: () => { if (current() && client.current) void stop().catch(e => setError(e.message)) },
        onUserStartedSpeaking: () => { if (current()) { captionsBlocked.current = true; stream.interrupt(); stream.userSpeaking = true; setCaption(''); setState('user') } },
        onUserStoppedSpeaking: () => { if (current()) { stream.userSpeaking = false; setState('thinking') } },
        onBotStartedSpeaking: () => { if (current()) { stream.botSpeaking = true; setState('bot') } },
        onBotStoppedSpeaking: () => { if (current()) { stream.botSpeaking = false; setState('listening') } },
        onBotTtsText: data => { if (current() && !captionsBlocked.current) setCaption(value => `${value} ${data.text}`.trim().slice(-500)) },
        onServerMessage: message => { if (current() && isAvatarEvent(message)) {
          if (message.type === 'playback_start') { captionsBlocked.current = false; setCaption('') }
          if (message.type === 'interrupt') { captionsBlocked.current = true; stream.interrupt(); setCaption('') }
          stream.emit(message)
        } },
        onError: () => { if (current()) { setError('Соединение прервано. История сохранена; повторите подключение.'); void stop().catch(e => setError(e.message)) } },
      } })
      client.current = bot
      await bot.initDevices()
      if (!current()) { await bot.disconnect(); return }
      const url = new URL(prepared.path, location.origin); url.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
      await bot.connect({ wsUrl: url.toString() })
    } catch (e) {
      if (current()) {
        setError((e as Error).name === 'NotAllowedError' ? 'Микрофон запрещён. Разрешите его в браузере и повторите запуск или продолжите переписку.' : (e as Error).message)
        await stop().catch(() => setError('Не удалось подтвердить остановку. Повторите отключение.'))
      }
    }
  }
  const interrupt = () => { captionsBlocked.current = true; stream.interrupt(); setCaption(''); client.current?.sendClientMessage('interrupt'); setState('listening') }
  return <section className="selected-voice team-voice" aria-label="Разговор с 3D-персонажем">
    <div className="team-stage"><AvatarStage stream={stream} name={name} />
      {state === 'off' && !preview && <div className="team-brief">{intro}<button className="button secondary" onClick={() => setPreview(true)}>Посмотреть персонажа без микрофона</button></div>}
      {state === 'off' && preview && <button className="button secondary team-return-brief" onClick={() => setPreview(false)}>Вернуться к вводной</button>}
      {caption && <p className="call-subtitle" aria-label="Субтитры собеседника">{caption}</p>}
      <span className="call-nameplate">{name} · ИИ-персонаж</span>
    </div>
    <div className="call-controls">
      <div className="voice-state" role="status">{{ off: 'Бэкенд команды · Pipecat и локальный 3D', connecting: 'Подключаем голос…', stopping: 'Останавливаем разговор…', cleanup_failed: 'Остановка ещё не подтверждена', listening: 'Слушаю вас', user: 'Вы говорите', thinking: 'Собеседник обдумывает ответ…', bot: 'Собеседник говорит' }[state]}</div>
      <div className="call-toolbar">
        {state === 'cleanup_failed' && <button className="button primary" onClick={() => void stop().catch(e => setError(e.message))}>Повторить отключение</button>}
        {state === 'off' ? <button className="button primary" disabled={disabled || startDisabled} onClick={() => void connect()}><Icon name="mic" size={18} />Начать диалог</button> : <>
          <button className="button secondary" disabled={state === 'connecting' || state === 'stopping'} onClick={async () => { try { await client.current?.enableMic(muted); setMuted(!muted) } catch { setError('Не удалось переключить микрофон.') } }} aria-pressed={muted}><Icon name={muted ? 'micOff' : 'mic'} size={18} />{muted ? 'Включить микрофон' : 'Выключить микрофон'}</button>
          <button className="button secondary" disabled={!['bot', 'thinking'].includes(state)} onClick={interrupt}>Перебить</button>
          <button className="button secondary" disabled={state === 'stopping'} onClick={() => void stop().catch(e => setError(e.message))}>Приостановить</button>
        </>}
        <button className="button call-end" disabled={disabled || state === 'stopping'} onClick={onEnd}>Завершить</button>
      </div>
      {error && <div className="notice warning" role="alert">{error}</div>}
    </div>
  </section>
}
