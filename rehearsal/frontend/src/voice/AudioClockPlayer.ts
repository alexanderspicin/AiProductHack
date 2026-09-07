/** Browser rendering adapter for Pipecat PCM. No VAD, STT, TTS or turn logic. */
export type TimedEvent = { type: string; utterance_id: number; audio_offset_ms?: number; [key: string]: unknown }

export class AudioClockPlayer {
  private context: AudioContext | null = null
  private sources = new Set<AudioBufferSourceNode>()
  private starts = new Map<number, number>()
  private events: TimedEvent[] = []
  private cursor = 0
  private active = 0
  private cancelledThrough = 0
  private blocked = true
  constructor(private deliver: (event: TimedEvent) => void) {}

  async unlock() {
    this.context ??= new AudioContext({ sampleRate: 24000 })
    await this.context.resume()
  }
  event(event: TimedEvent) {
    if (event.type === 'interrupt') { this.interrupt(); return }
    if (event.utterance_id <= this.cancelledThrough) return
    if (event.type === 'playback_start') { this.active = event.utterance_id; this.blocked = false }
    if (this.blocked) return
    this.events.push(event)
  }
  buffer(data: ArrayBuffer | Int16Array) {
    const pcm = data instanceof Int16Array ? data : new Int16Array(data)
    if (!this.context || this.blocked || !pcm.length) return pcm
    const context = this.context
    const buffer = context.createBuffer(1, pcm.length, 24000)
    const channel = buffer.getChannelData(0)
    for (let i = 0; i < pcm.length; i++) channel[i] = pcm[i] / 32768
    const source = context.createBufferSource()
    source.buffer = buffer; source.connect(context.destination)
    const start = Math.max(context.currentTime + .025, this.cursor)
    if (!this.starts.has(this.active)) this.starts.set(this.active, start)
    this.cursor = start + buffer.duration
    this.sources.add(source)
    source.onended = () => { this.sources.delete(source); source.disconnect() }
    source.start(start)
    return pcm
  }
  tick() {
    if (!this.context) return
    const timestamp = this.context.getOutputTimestamp?.()
    const outputTime = timestamp?.contextTime ?? 0
    const now = outputTime > 0 ? outputTime
      : this.context.currentTime - (this.context.outputLatency || this.context.baseLatency || 0)
    const pending: TimedEvent[] = []
    for (const event of this.events) {
      const start = this.starts.get(event.utterance_id)
      if (start === undefined || now < start + (event.audio_offset_ms || 0) / 1000) pending.push(event)
      else this.deliver(event)
    }
    this.events = pending
  }
  interrupt() {
    this.cancelledThrough = Math.max(this.cancelledThrough, this.active)
    this.blocked = true
    this.events = []; this.starts.clear(); this.cursor = 0
    for (const source of this.sources) { try { source.stop() } catch { /* already stopped */ } }
    this.sources.clear()
  }
  async close() {
    this.interrupt()
    const context = this.context; this.context = null
    this.active = 0; this.cancelledThrough = 0
    await context?.close()
  }
}
