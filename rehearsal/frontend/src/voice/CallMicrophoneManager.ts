import { ClockedMediaManager } from './ClockedMediaManager'

/** Daily acquires the microphone even when muted. Defer it for text-only callers. */
export class CallMicrophoneManager extends ClockedMediaManager {
  private inputReady = false
  private callConnected = false
  private generation = 0

  override async initialize() {
    if (!this._micEnabled || this.inputReady) return
    const generation = this.generation
    await super.initialize()
    if (generation !== this.generation) {
      await super.disconnect()
      throw new DOMException('Подключение отменено', 'AbortError')
    }
    this.inputReady = true
  }
  override async connect() {
    this.callConnected = true
    if (!this._micEnabled) return
    await this.initialize()
    await super.connect()
  }
  override async enableMic(enable: boolean) {
    if (!enable) return super.enableMic(false)
    this._micEnabled = true
    try {
      await this.initialize()
      if (this.callConnected) await super.connect()
      await super.enableMic(true)
    } catch (error) {
      await super.enableMic(false)
      throw error
    }
  }
  override async disconnect() {
    this.generation++
    this.callConnected = false
    this.inputReady = false
    this._micEnabled = false
    await super.disconnect()
  }
}
