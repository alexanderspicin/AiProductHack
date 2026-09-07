import { afterEach, expect, it, vi } from 'vitest'
import { AudioClockPlayer, type TimedEvent } from '../src/voice/AudioClockPlayer'

afterEach(() => vi.unstubAllGlobals())

it('renders subtitles/visemes only when their PCM is audible and drops all cancelled events', async () => {
  let now = 0
  const sources: { start: ReturnType<typeof vi.fn>; stop: ReturnType<typeof vi.fn> }[] = []
  class Context {
    currentTime = 0
    destination = {}
    getOutputTimestamp() { return { contextTime: now } }
    async resume() {}
    async close() {}
    createBuffer(_channels: number, length: number, rate: number) { return { duration: length / rate, getChannelData: () => new Float32Array(length) } }
    createBufferSource() {
      const source = { start: vi.fn(), stop: vi.fn(), connect() {}, disconnect() {}, buffer: null, onended: null }
      sources.push(source); return source
    }
  }
  vi.stubGlobal('AudioContext', Context)
  const delivered: TimedEvent[] = []
  const player = new AudioClockPlayer(event => delivered.push(event))
  await player.unlock()
  player.event({ type: 'playback_start', utterance_id: 1 })
  player.event({ type: 'subtitle', utterance_id: 1, text: 'Здравствуйте', audio_offset_ms: 500 })
  player.tick()
  expect(delivered).toHaveLength(0)
  player.buffer(new Int16Array(24000))
  now = .03; player.tick()
  expect(delivered.map(e => e.type)).toEqual(['playback_start'])
  now = .53; player.tick()
  expect(delivered.at(-1)?.text).toBe('Здравствуйте')
  player.event({ type: 'subtitle', utterance_id: 1, text: 'Устаревшее', audio_offset_ms: 900 })
  player.interrupt()
  expect(sources[0].stop).toHaveBeenCalledOnce()
  player.buffer(new Int16Array(100))
  player.event({ type: 'playback_start', utterance_id: 1 })
  player.event({ type: 'subtitle', utterance_id: 1, text: 'Ещё устаревшее' })
  now = 3; player.tick()
  expect(sources).toHaveLength(1)
  expect(delivered).toHaveLength(2)
  player.event({ type: 'playback_start', utterance_id: 2 })
  player.buffer(new Int16Array(2400))
  player.tick()
  expect(delivered.at(-1)?.utterance_id).toBe(2)
  await player.close()
})
