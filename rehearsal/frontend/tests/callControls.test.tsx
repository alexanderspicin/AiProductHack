import { createRef } from 'react'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
const mock = vi.hoisted(() => ({ bots: [] as any[], media: [] as any[], remote: [] as any[], deny: false, delay: null as null | Promise<void> }))
vi.mock('@pipecat-ai/client-js', () => ({ PipecatClient: class {
  sendText = vi.fn(async () => {})
  sendClientMessage = vi.fn()
  disconnect = vi.fn(async () => {})
  constructor(public options: any) { mock.bots.push(this) }
  async initDevices() { if (mock.delay) await mock.delay; if (mock.deny) { mock.deny = false; throw new DOMException('Denied', 'NotAllowedError') } }
  async connect() { this.options.callbacks.onBotReady() }
} }))
vi.mock('@pipecat-ai/websocket-transport', () => ({ WebSocketTransport: class {} }))
vi.mock('../src/voice/CallMicrophoneManager', () => ({ CallMicrophoneManager: class { enableMic = vi.fn(async () => {}); constructor() { mock.media.push(this) } } }))
vi.mock('../src/voice/RemoteAvatar', () => ({
  bounded: (promise: Promise<unknown>) => promise,
  RemoteAvatar: class { unlock = vi.fn(async () => {}); connect = vi.fn(async () => {}); close = vi.fn(async () => {}); interrupt = vi.fn(); start = vi.fn(); chunk = vi.fn(); end = vi.fn(); constructor() { mock.remote.push(this) } },
}))
import { SelectedVoiceTools } from '../src/voice/SelectedVoiceTools'
const sendRef = () => ({ current: null as ((text: string) => Promise<void>) | null })
const renderCall = () => {
  const send = sendRef(), stop = createRef<(() => Promise<void>) | null>(), end = vi.fn(), ready = vi.fn(), connection = vi.fn()
  render(<SelectedVoiceTools sessionId="call-fixture" name="Татьяна" profile="anam_tatiana" intro={<p>Вводная перед звонком</p>} allowAudioFallback disabled={false} onConnection={connection} onReady={ready} onEnd={end} sendRef={send} stopRef={stop} />)
  return { send, stop, end, ready, connection }
}
beforeEach(() => {
  mock.bots = []; mock.media = []; mock.remote = []; mock.deny = false; mock.delay = null
  vi.stubGlobal('fetch', vi.fn(async (url: string) => new Response(JSON.stringify(url.endsWith('/prepare') ? { path: '/ws', max_seconds: 180, provider: 'anam' } : {}), { status: 200 })))
})
afterEach(async () => { cleanup(); await act(async () => {}); vi.unstubAllGlobals(); vi.clearAllMocks() })

test('one start, no automatic media call, mic preference applies, and text uses the same bot', async () => {
  const call = renderCall()
  expect(screen.getAllByRole('button', { name: 'Начать диалог' })).toHaveLength(1)
  expect(screen.queryByRole('button', { name: 'Видео и текст' })).toBeNull()
  expect(fetch).not.toHaveBeenCalled()
  expect(screen.getByText('Вводная перед звонком')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Выключить микрофон' }))
  fireEvent.click(screen.getByRole('button', { name: 'Начать диалог' }))
  await waitFor(() => expect(call.ready).toHaveBeenCalledOnce())
  expect(screen.queryByText('Вводная перед звонком')).toBeNull()
  expect(mock.bots[0].options.enableMic).toBe(false)
  expect(mock.bots[0].options.enableCam).toBe(false)
  await act(async () => { await call.send.current!('Мой вопрос') })
  expect(mock.bots[0].sendText).toHaveBeenCalledWith('Мой вопрос', { run_immediately: true, audio_response: true })
  fireEvent.click(screen.getByRole('button', { name: 'Включить микрофон' }))
  await waitFor(() => expect(mock.media[0].enableMic).toHaveBeenCalledWith(true))
  fireEvent.click(screen.getByRole('button', { name: 'Выключить микрофон' }))
  await waitFor(() => expect(mock.media[0].enableMic).toHaveBeenLastCalledWith(false))
  fireEvent.click(screen.getByRole('button', { name: 'Перебить' }))
  expect(mock.bots[0].sendClientMessage).toHaveBeenCalledWith('interrupt')
  fireEvent.click(screen.getByRole('button', { name: 'Завершить' }))
  expect(call.end).toHaveBeenCalledOnce()
  await act(async () => { await call.stop.current!() })
  expect(mock.bots[0].disconnect).toHaveBeenCalledOnce()
  expect(mock.remote[0].close).toHaveBeenCalledOnce()
  expect(call.send.current).toBeNull()
  expect(screen.getByRole('button', { name: 'Продолжить диалог' })).toBeTruthy()
  expect(screen.queryByText('Вводная перед звонком')).toBeNull()
})

test('denied microphone keeps video and text available without a second start', async () => {
  mock.deny = true
  const call = renderCall()
  fireEvent.click(screen.getByRole('button', { name: 'Начать диалог' }))
  await waitFor(() => expect(call.ready).toHaveBeenCalledOnce())
  expect(mock.media[0].enableMic).toHaveBeenCalledWith(false)
  expect(screen.getByText(/Микрофон недоступен/)).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Включить микрофон' })).toBeTruthy()
  expect(mock.remote[0].connect).toHaveBeenCalledOnce()
})

test('cancel before microphone initialization never reserves provider minutes', async () => {
  let resolve!: () => void
  mock.delay = new Promise<void>(r => { resolve = r })
  const call = renderCall()
  fireEvent.click(screen.getByRole('button', { name: 'Начать диалог' }))
  await screen.findByRole('button', { name: 'Отменить подключение' })
  fireEvent.click(screen.getByRole('button', { name: 'Отменить подключение' }))
  await act(async () => { resolve() })
  await screen.findByRole('button', { name: 'Начать диалог' })
  expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).endsWith('/prepare'))).toBe(false)
  expect(call.ready).not.toHaveBeenCalled()
})
