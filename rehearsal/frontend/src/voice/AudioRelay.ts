/** Generation-aware output queue. Input detection and LLM stay on the server. */
export type AvatarAudioEvent = { type: 'avatar_audio'; kind: 'start' | 'chunk' | 'end' | 'interrupt'; epoch: number; sequence: number; audio?: string }
export interface AudioSink {
  start(id: string): Promise<void>
  chunk(audio: string): void
  end(): void
  interrupt(): void
}

export function isAvatarAudioEvent(value: unknown): value is AvatarAudioEvent {
  if (!value || typeof value !== 'object') return false
  const v = value as AvatarAudioEvent
  return v.type === 'avatar_audio' && ['start', 'chunk', 'end', 'interrupt'].includes(v.kind)
    && Number.isSafeInteger(v.epoch) && v.epoch >= 0 && Number.isSafeInteger(v.sequence) && v.sequence >= 0
    && (v.kind !== 'chunk' || (typeof v.audio === 'string' && v.audio.length <= 6400 && /^[A-Za-z0-9+/]*={0,2}$/.test(v.audio)))
}

export class AudioRelay {
  private epoch = 0
  private sequence = 0
  private active = false
  private suspended = false
  private speaking = false
  private version = 0
  private pending = 0
  private chain = Promise.resolve()
  constructor(private sink: AudioSink, private fail: (error: Error) => void) {}

  userSpeaking(value: boolean) { this.speaking = value; if (value) this.suspend() }
  suspend() {
    this.version++; this.active = false; this.pending = 0; this.chain = Promise.resolve()
    if (!this.suspended) { this.suspended = true; this.sink.interrupt() }
  }
  event(event: AvatarAudioEvent) {
    if (event.epoch < this.epoch) return
    if (event.kind === 'interrupt') { this.epoch = event.epoch; this.suspend(); return }
    if (event.kind === 'start') {
      if (event.sequence <= this.sequence || this.speaking) return
      this.epoch = event.epoch; this.sequence = event.sequence; this.active = true; this.suspended = false
    } else if (!this.active || event.sequence !== this.sequence || event.epoch !== this.epoch) return
    if (++this.pending > 600) { this.suspend(); this.fail(new Error('Видео не успевает за звуком. Продолжите без видео.')); return }
    const version = this.version
    this.chain = this.chain.then(async () => {
      if (version !== this.version) return
      if (event.kind === 'start') await this.sink.start(`${event.epoch}-${event.sequence}`)
      else if (event.kind === 'chunk') this.sink.chunk(event.audio!)
      else this.sink.end()
    }).catch(() => {
      if (version === this.version) { this.suspend(); this.fail(new Error('Не удалось передать звук персонажу. Можно продолжить текстом или без видео.')) }
    }).finally(() => { if (version === this.version) this.pending-- })
    if (event.kind === 'end') this.active = false
  }
  async flushed() { await this.chain }
}
