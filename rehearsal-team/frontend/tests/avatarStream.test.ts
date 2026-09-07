import { describe, expect, it } from 'vitest'
import { AvatarStream } from '../src/voice/AvatarStream'
import { VisemeDriver } from '../src/avatar/visemeDriver'
import { AvatarPresence } from '../src/avatar/presence'
import { BlendshapeCompositor } from '../src/avatar/blendshapeCompositor'

describe('Pipecat avatar interruption', () => {
  it('drops late visemes after interrupt, accepts fresh utterances on reconnect', () => {
    const stream = new AvatarStream(), presence = new AvatarPresence()
    const compositor = new BlendshapeCompositor()
    const applied: Record<string, number>[] = []
    compositor.set = (_layer, weights) => { applied.push(weights) }
    const driver = new VisemeDriver(presence, compositor)
    stream.subscribe(event => driver.handleAvatarEvent(event))
    stream.emit({ type: 'playback_start', utterance_id: 1 })
    stream.emit({ type: 'viseme', utterance_id: 1, mouth_open: 1, blendshapes: { viseme_aa: 1 } })
    driver.update(.1)
    expect(applied.at(-1)?.viseme_aa).toBeGreaterThan(0)
    stream.emit({ type: 'interrupt', utterance_id: 1 })
    stream.emit({ type: 'viseme', utterance_id: 1, mouth_open: 1, blendshapes: { viseme_aa: 1 } })
    driver.update(.1)
    expect(applied.at(-1)?.viseme_aa || 0).toBe(0)
    stream.reset()
    stream.emit({ type: 'playback_start', utterance_id: 1 })
    stream.emit({ type: 'viseme', utterance_id: 1, mouth_open: .5, blendshapes: { viseme_aa: .5 } })
    driver.update(.1)
    expect(applied.at(-1)?.viseme_aa).toBeGreaterThan(0)
  })
})
