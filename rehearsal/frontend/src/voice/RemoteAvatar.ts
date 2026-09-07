import type { AudioSink } from './AudioRelay'

export type PreparedAvatar = {
  path: string; provider: 'tavus' | 'anam' | 'audio'; profile: string; lease: string; max_seconds: number
  session_token?: string; conversation_url?: string; conversation_id?: string
}
type Driver = { chunk(audio: string, id: string): void; end(id: string): void; interrupt(): void; close(): Promise<void> }

export async function bounded<T>(promise: Promise<T>, ms: number, message: string): Promise<T> {
  let timer: ReturnType<typeof setTimeout>
  try { return await Promise.race([promise, new Promise<never>((_, reject) => { timer = setTimeout(() => reject(new Error(message)), ms) })]) }
  finally { clearTimeout(timer!) }
}

/** Owns the sole audible media element. Raw remote audio is analysed, never played twice. */
export class RemoteAvatar implements AudioSink {
  private driver: Driver | null = null
  private context: AudioContext | null = null
  private source: MediaStreamAudioSourceNode | null = null
  private analyser: AnalyserNode | null = null
  private samples = new Float32Array(512)
  private frame = 0
  private closed = false
  private version = 0
  private utterance = ''
  private quietSince = 0
  private interruptedAt = 0
  private draining = false
  private audible = false
  private quietWaiters = new Set<() => void>()
  constructor(private video: HTMLVideoElement, private onSpeaking: (speaking: boolean) => void, private onError: (error: Error) => void) {}

  async unlock() {
    this.context ??= new AudioContext()
    await this.context.resume()
  }
  private async attach(stream: MediaStream) {
    if (this.closed) return
    this.source?.disconnect()
    this.video.srcObject = stream
    this.video.muted = true
    this.source = this.context!.createMediaStreamSource(new MediaStream(stream.getAudioTracks()))
    this.analyser = this.context!.createAnalyser(); this.analyser.fftSize = 512
    this.source.connect(this.analyser)
    await this.video.play()
    if (!this.frame) this.tick()
  }
  private tick = () => {
    if (this.closed) return
    this.analyser?.getFloatTimeDomainData(this.samples)
    const rms = Math.sqrt(this.samples.reduce((s, x) => s + x * x, 0) / this.samples.length)
    const now = performance.now(), loud = rms > .008
    if (loud) this.quietSince = 0
    else this.quietSince ||= now
    if (this.draining && this.quietSince && now - Math.max(this.quietSince, this.interruptedAt) >= 220) {
      this.draining = false
      for (const done of this.quietWaiters) done()
      this.quietWaiters.clear()
    }
    const speaking = loud && !this.video.muted
    if (speaking && !this.audible) { this.audible = true; this.onSpeaking(true) }
    if (!speaking && this.audible && this.quietSince && now - this.quietSince > 300) { this.audible = false; this.onSpeaking(false) }
    this.frame = requestAnimationFrame(this.tick)
  }

  async connect(prepared: PreparedAvatar) {
    await this.unlock()
    if (prepared.provider === 'anam') {
      const { createClient, AnamEvent } = await import('@anam-ai/js-sdk')
      if (this.closed) return
      const client = createClient(prepared.session_token!, { disableInputAudio: true,
        api: { retry: { maxAttempts: 1 }, requestTimeoutMs: 15000 }, metrics: { disableClientMetrics: true } })
      let input: ReturnType<typeof client.createAgentAudioInputStream> | null = null
      this.driver = {
        chunk: audio => { if (!input) throw new Error('Аватар ещё не готов'); input.sendAudioChunk(audio) },
        end: () => input?.endSequence(),
        interrupt: () => { if (client.isStreaming()) { client.interruptPersona(); input?.endSequence() } },
        close: () => client.stopStreaming(),
      }
      client.addListener(AnamEvent.CONNECTION_CLOSED, () => { if (!this.closed) this.onError(new Error('Соединение с видео закрыто. История сохранена.')) })
      const streams = await client.stream()
      if (this.closed) { await client.stopStreaming(); return }
      await this.attach(new MediaStream([...new Set(streams.flatMap(s => s.getTracks()))]))
      input = client.createAgentAudioInputStream({ encoding: 'pcm_s16le', sampleRate: 24000, channels: 1 })
    } else if (prepared.provider === 'tavus') {
      const { default: Daily } = await import('@daily-co/daily-js')
      if (this.closed) return
      const call = Daily.createCallObject({ audioSource: false, videoSource: false,
        startAudioOff: true, startVideoOff: true, allowMultipleCallInstances: true })
      const send = (event_type: string, properties?: object) => call.sendAppMessage({ message_type: 'conversation', event_type,
        conversation_id: prepared.conversation_id, ...(properties ? { properties } : {}) }, '*')
      this.driver = {
        chunk: (audio, id) => send('conversation.echo', { modality: 'audio', audio, sample_rate: 24000, inference_id: id, done: false }),
        end: id => send('conversation.echo', { modality: 'audio', audio: btoa('\0'.repeat(1920)), sample_rate: 24000, inference_id: id, done: true }),
        interrupt: () => { send('conversation.interrupt') },
        close: async () => { try { await call.leave() } finally { await call.destroy() } },
      }
      let attached = ''
      let ready!: () => void
      const mediaReady = new Promise<void>(resolve => { ready = resolve })
      const update = () => {
        if (this.closed) return
        const participant = Object.values(call.participants()).find(p => !p.local && p.tracks.video.persistentTrack && p.tracks.audio.persistentTrack)
        if (!participant) return
        const tracks = [participant.tracks.video.persistentTrack!, participant.tracks.audio.persistentTrack!]
        const trackKey = tracks.map(t => t.id).join(':')
        if (trackKey === attached) return
        attached = trackKey
        void this.attach(new MediaStream(tracks)).then(ready).catch(this.onError)
      }
      call.on('participant-updated', update).on('participant-joined', update).on('track-started', update)
      call.on('error', () => { if (!this.closed) this.onError(new Error('Не удалось подключить видео. Можно продолжить без него.')) })
      call.on('left-meeting', () => { if (!this.closed) this.onError(new Error('Видеосессия завершена. Переписка сохранена.')) })
      await call.join({ url: prepared.conversation_url!, audioSource: false, videoSource: false })
      if (this.closed) { await call.destroy(); return }
      update(); await bounded(mediaReady, 20000, 'Видео не пришло за 20 секунд. Попробуйте разговор без видео.')
    }
  }

  async start(id: string) {
    const version = this.version
    if (this.draining) {
      let resolve!: () => void
      const drained = new Promise<void>(r => { resolve = r; this.quietWaiters.add(r) })
      try { await bounded(drained, 1600, 'Видео не подтвердило остановку. Перейдите к разговору без видео.') }
      finally { this.quietWaiters.delete(resolve) }
    }
    if (this.closed || version !== this.version) return
    this.utterance = id
    this.video.muted = false
    await this.video.play()
  }
  chunk(audio: string) { if (!this.closed && this.utterance) this.driver?.chunk(audio, this.utterance) }
  end() { if (!this.closed && this.utterance) this.driver?.end(this.utterance) }
  interrupt() {
    this.version++; this.utterance = ''; this.video.muted = true; this.video.pause()
    this.audible = false; this.onSpeaking(false)
    this.interruptedAt = performance.now(); this.draining = true
    try { this.driver?.interrupt() } catch { /* Stay muted; caller can disconnect safely. */ }
  }
  async close() {
    if (this.closed) return
    this.closed = true; this.version++; this.video.muted = true; this.video.pause()
    cancelAnimationFrame(this.frame)
    for (const done of this.quietWaiters) done()
    this.quietWaiters.clear()
    this.source?.disconnect()
    const driver = this.driver; this.driver = null
    try { await bounded(driver?.close() || Promise.resolve(), 4000, 'Видео ещё закрывается') }
    finally { this.video.srcObject = null; await this.context?.close(); this.context = null }
  }
}
