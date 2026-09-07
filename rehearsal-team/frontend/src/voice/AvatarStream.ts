import type { AvatarEvent } from '../protocol/avatarProtocol'

export class AvatarStream {
  botSpeaking = false
  userSpeaking = false
  private utterance = 0
  private listeners = new Set<(event: AvatarEvent) => void>()
  private offset = 0
  private maximum = 0
  subscribe(listener: (event: AvatarEvent) => void) {
    this.listeners.add(listener)
    return () => { this.listeners.delete(listener) }
  }
  emit(event: AvatarEvent) {
    const mapped = { ...event, utterance_id: event.utterance_id + this.offset }
    if (event.type === 'playback_start') this.utterance = mapped.utterance_id
    this.maximum = Math.max(this.maximum, mapped.utterance_id)
    this.listeners.forEach(listener => listener(mapped))
  }
  reset() {
    this.interrupt()
    this.offset = this.maximum + 1
  }
  interrupt() {
    this.botSpeaking = false; this.userSpeaking = false
    this.listeners.forEach(listener => listener({ type: 'interrupt', utterance_id: this.utterance }))
  }
}
