import { useEffect, useRef, useState, type MutableRefObject } from 'react'
import { PipecatClient } from '@pipecat-ai/client-js'
import { WebSocketTransport } from '@pipecat-ai/websocket-transport'
import { AvatarStage } from '../avatar/AvatarStage'
import { isAvatarEvent } from '../protocol/avatarProtocol'
import { AvatarStream } from './AvatarStream'
import { AudioClockPlayer, type TimedEvent } from './AudioClockPlayer'
import { ClockedMediaManager } from './ClockedMediaManager'
import { api } from '../text/api'
import { Icon } from '../text/ui'

type Props = {
  sessionId: string; name: string; disabled: boolean
  onConnection: (connected: boolean) => void
  sendRef: MutableRefObject<((text: string) => Promise<void>) | null>
}

export function VoiceTools({ sessionId, name, disabled, onConnection, sendRef }: Props) {
  const [stream] = useState(() => new AvatarStream())
  const client = useRef<PipecatClient | null>(null)
  const [state, setState] = useState('off')
  const [error, setError] = useState('')
  const [muted, setMuted] = useState(false)
  const [caption, setCaption] = useState('')
  const [subtitle, setSubtitle] = useState('')
  const [playback] = useState(() => new AudioClockPlayer(event => {
    if (event.type === 'subtitle') setSubtitle(current => `${current} ${String(event.text || '')}`.trim().slice(-350))
    else if (isAvatarEvent(event)) {
      if (event.type === 'playback_start') { stream.botSpeaking = true; setSubtitle('') }
      if (event.type === 'playback_end') stream.botSpeaking = false
      stream.emit(event)
    }
  }))
  const generation = useRef(0)
  const callback = useRef(onConnection)
  callback.current = onConnection

  const disconnect = async () => {
    const version = ++generation.current
    const active = client.current; client.current = null
    playback.interrupt(); stream.reset(); setSubtitle(''); setState('disconnecting'); callback.current(false); sendRef.current = null
    try { await active?.disconnect() } catch { /* Server may already have disconnected. */ }
    await api(`/sessions/${sessionId}/voice/stop`, 'POST').catch(() => {})
    await playback.close()
    if (version === generation.current) setState('off')
  }
  useEffect(() => {
    let frame = 0
    const tick = () => { playback.tick(); frame = requestAnimationFrame(tick) }
    frame = requestAnimationFrame(tick)
    return () => { cancelAnimationFrame(frame); generation.current++; stream.reset(); void client.current?.disconnect(); client.current = null; sendRef.current = null; void playback.close() }
  }, [sessionId, stream, playback, sendRef])
  useEffect(() => { if (disabled) void disconnect() }, [disabled])

  const connect = async () => {
    if (client.current) return
    const version = ++generation.current
    setError(''); setState('connecting'); setMuted(false)
    callback.current(true)
    try {
      await playback.unlock()
      const prepared = await api<{ path: string }>(`/sessions/${sessionId}/voice/prepare`, 'POST')
      if (version !== generation.current) return
      const current = () => version === generation.current
      const bot = new PipecatClient({
        transport: new WebSocketTransport({ mediaManager: new ClockedMediaManager(playback) }), enableMic: true, enableCam: false,
        callbacks: {
          onBotReady: () => { if (current()) {
            sendRef.current = async text => { playback.interrupt(); stream.interrupt(); setSubtitle(''); await bot.sendText(text, { run_immediately: true, audio_response: true }) }
            setState('listening'); callback.current(true)
          } },
          onDisconnected: () => { if (current()) void disconnect() },
          onUserStartedSpeaking: () => { if (current()) { playback.interrupt(); stream.interrupt(); setSubtitle(''); stream.userSpeaking = true; setState('user') } },
          onUserStoppedSpeaking: () => { if (current()) { stream.userSpeaking = false; setState('thinking') } },
          onBotStartedSpeaking: () => { if (current()) setState('bot') },
          onBotStoppedSpeaking: () => { if (current()) setState('listening') },
          onUserTranscript: data => { if (current()) setCaption(data.text) },
          onServerMessage: message => {
            if (!current() || typeof message !== 'object' || !message) return
            if (isAvatarEvent(message) || ('type' in message && message.type === 'subtitle')) {
              const event = message as TimedEvent
              if (event.type === 'interrupt') { playback.interrupt(); stream.interrupt(); setSubtitle('') }
              else playback.event(event)
            }
          },
          onError: () => { if (current()) { setError('Ошибка голосового соединения. Отключитесь и повторите подключение.'); void disconnect() } },
        },
      })
      client.current = bot
      await bot.initDevices()
      if (!current()) { await bot.disconnect(); return }
      const url = new URL(prepared.path, window.location.origin)
      url.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
      await bot.connect({ wsUrl: url.toString() })
    } catch (e) {
      if (version === generation.current) {
        setError((e as Error).name === 'NotAllowedError' ? 'Разрешите браузеру доступ к микрофону.' : (e as Error).message)
        await disconnect()
      }
    }
  }

  return <section className="voice-tools" aria-label="Голос и персонаж">
    <AvatarStage stream={stream} name={name} />
    <div className="voice-controls">
      <div className="voice-state" role="status"><span className={`voice-dot ${state === 'user' || state === 'bot' ? 'active' : ''}`} />
        {{ off: 'Разговор не подключён', connecting: 'Подключаем разговор…', disconnecting: 'Отключаем разговор…', listening: 'Слушаю вас', user: 'Вы говорите', thinking: 'Собеседник обдумывает ответ…', bot: 'Собеседник говорит' }[state]}
      </div>
      <div className="voice-buttons">
        {state === 'off' ? <button className="button primary" onClick={() => void connect()} disabled={disabled}><Icon name="mic" size={17} />Начать разговор</button>
          : <><button className="button secondary" onClick={() => { client.current?.enableMic(muted); setMuted(!muted) }} disabled={state === 'connecting' || state === 'disconnecting'}><Icon name={muted ? 'micOff' : 'mic'} size={17} />{muted ? 'Включить микрофон' : 'Выключить микрофон'}</button><button className="button stop-button" disabled={state === 'disconnecting'} onClick={() => void disconnect()}>Отключиться</button></>}
      </div>
      <p className="voice-footnote">Говорите естественно. Можно перебить собеседника и делать паузы внутри фразы.</p>
      {caption && state !== 'off' && <p className="voice-footnote" aria-live="polite">Вы: {caption}</p>}
      {subtitle && <p className="voice-subtitles" aria-live="polite" aria-label="Субтитры собеседника">{subtitle}</p>}
      {error && <div className="voice-error" role="alert">{error}</div>}
    </div>
  </section>
}
