import { describe, it, expect, vi } from 'vitest'
import { AudioRelay, type AudioSink, type AvatarAudioEvent } from '../src/voice/AudioRelay'

function fixture() {
  const sink: AudioSink = { start: vi.fn(async () => {}), chunk: vi.fn(), end: vi.fn(), interrupt: vi.fn() }
  const fail = vi.fn(), relay = new AudioRelay(sink, fail)
  const send = (kind: AvatarAudioEvent['kind'], epoch = 0, sequence = 1) => relay.event({ type: 'avatar_audio', kind, epoch, sequence, audio: 'AAAA' })
  return { sink, relay, fail, send }
}
describe('generation-aware avatar audio', () => {
  it('forwards every sentence in order without double playback', async () => {
    const { sink, relay, send } = fixture()
    send('start'); send('chunk'); send('end'); send('start', 0, 2); send('chunk', 0, 2); send('end', 0, 2)
    await relay.flushed()
    expect(sink.start).toHaveBeenCalledTimes(2); expect(sink.chunk).toHaveBeenCalledTimes(2); expect(sink.end).toHaveBeenCalledTimes(2)
  })
  it('mutes synchronously before any transcript and drops pending old chunks', async () => {
    const { sink, relay, send } = fixture()
    send('start'); send('chunk'); relay.userSpeaking(true)
    expect(sink.interrupt).toHaveBeenCalledTimes(1)
    send('interrupt', 1); send('chunk'); send('end'); await relay.flushed()
    expect(sink.chunk).not.toHaveBeenCalled()
    relay.userSpeaking(false); send('start', 1, 2); send('chunk', 1, 2); await relay.flushed()
    expect(sink.chunk).toHaveBeenCalledTimes(1)
  })
  it('handles interrupt notification before user-speaking callback', async () => {
    const { sink, relay, send } = fixture()
    send('start'); await relay.flushed(); send('interrupt', 1); relay.userSpeaking(true)
    send('start', 0, 2); relay.userSpeaking(false); send('start', 1, 3); send('chunk', 1, 3)
    await relay.flushed(); expect(sink.chunk).toHaveBeenCalledTimes(1)
  })
  it('does not let a blocked previous start send audio after cancellation', async () => {
    const { sink, relay, send } = fixture()
    let release!: () => void
    sink.start = vi.fn(() => new Promise<void>(r => { release = r }))
    send('start'); send('chunk'); await Promise.resolve()
    relay.suspend(); release(); await relay.flushed(); await Promise.resolve()
    expect(sink.chunk).not.toHaveBeenCalled()
  })
})
