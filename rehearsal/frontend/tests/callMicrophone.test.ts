import { beforeEach, expect, test, vi } from 'vitest'

const operations = vi.hoisted(() => ({ initialize: vi.fn(async () => {}), connect: vi.fn(async () => {}), disconnect: vi.fn(async () => {}), toggle: vi.fn(async (_on: boolean) => {}) }))
vi.mock('../src/voice/ClockedMediaManager', () => ({ ClockedMediaManager: class {
  protected _micEnabled = true
  setClientOptions(options: { enableMic: boolean }) { this._micEnabled = options.enableMic }
  async initialize() { await operations.initialize() }
  async connect() { await operations.connect() }
  async disconnect() { await operations.disconnect() }
  async enableMic(on: boolean) { this._micEnabled = on; await operations.toggle(on) }
} }))
import { CallMicrophoneManager } from '../src/voice/CallMicrophoneManager'
beforeEach(() => { vi.clearAllMocks(); operations.initialize.mockResolvedValue(undefined) })

test('text connection does not initialize microphone, enabling later keeps connection', async () => {
  const media = new CallMicrophoneManager({ buffer: d => new Int16Array(d as ArrayBuffer), interrupt() {} })
  media.setClientOptions({ enableMic: false })
  await media.initialize(); await media.connect()
  expect(operations.initialize).not.toHaveBeenCalled()
  expect(operations.connect).not.toHaveBeenCalled()
  await media.enableMic(true)
  expect(operations.initialize).toHaveBeenCalledOnce()
  expect(operations.connect).toHaveBeenCalledOnce()
  await media.enableMic(false)
  expect(operations.toggle).toHaveBeenLastCalledWith(false)
  await media.enableMic(true)
  expect(operations.initialize).toHaveBeenCalledOnce()
})

test('denied microphone can recover through a text-only connection', async () => {
  operations.initialize.mockRejectedValueOnce(new DOMException('Denied', 'NotAllowedError'))
  const media = new CallMicrophoneManager({ buffer: d => new Int16Array(d as ArrayBuffer), interrupt() {} })
  media.setClientOptions({ enableMic: true })
  await expect(media.initialize()).rejects.toThrow('Denied')
  await media.enableMic(false)
  await media.initialize(); await media.connect()
  expect(operations.initialize).toHaveBeenCalledOnce()
  expect(operations.connect).not.toHaveBeenCalled()
})

test('permission resolving after cancellation closes the late microphone', async () => {
  let permit!: () => void
  operations.initialize.mockImplementationOnce(() => new Promise<void>(resolve => { permit = resolve }))
  const media = new CallMicrophoneManager({ buffer: d => new Int16Array(d as ArrayBuffer), interrupt() {} })
  media.setClientOptions({ enableMic: true })
  const pending = media.initialize()
  await media.disconnect()
  permit()
  await expect(pending).rejects.toThrow('Подключение отменено')
  expect(operations.disconnect).toHaveBeenCalledTimes(2)
})
