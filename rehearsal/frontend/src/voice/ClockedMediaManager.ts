import { DailyMediaManager } from '@pipecat-ai/websocket-transport'
import type { AudioClockPlayer } from './AudioClockPlayer'

/** Official mediaManager extension point; Pipecat still owns microphone/transport. */
export class ClockedMediaManager extends DailyMediaManager {
  constructor(private playback: Pick<AudioClockPlayer, 'buffer' | 'interrupt'>) {
    super(false, true, undefined, undefined, 512, 16000, 24000)
  }
  override bufferBotAudio(data: ArrayBuffer | Int16Array) { return this.playback.buffer(data) }
  override async userStartedSpeaking() { this.playback.interrupt(); return super.userStartedSpeaking() }
  override async disconnect() { this.playback.interrupt(); return super.disconnect() }
}
