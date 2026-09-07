// Read-only audit: exercise the production component with simulated SDK events.
// All providers and HTTP requests are mocked. Passing tests confirm the defect,
// not acceptance of stale subtitles as correct behaviour.
import React from '../../../frontend/node_modules/react/index.js'
import { act, cleanup, fireEvent, render, screen, waitFor } from '../../../frontend/node_modules/@testing-library/react/dist/index.js'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
const mock = vi.hoisted(() => ({ bots: [] as any[] }))
vi.mock('@pipecat-ai/client-js', () => ({ PipecatClient: class {
  sendText = vi.fn(async () => {})
  sendClientMessage = vi.fn()
  disconnect = vi.fn(async () => {})
  constructor(public options: any) { mock.bots.push(this) }
  async initDevices() {}
  async connect() { this.options.callbacks.onBotReady() }
} }))
vi.mock('@pipecat-ai/websocket-transport', () => ({ WebSocketTransport: class {} }))
vi.mock('../../../frontend/src/voice/CallMicrophoneManager', () => ({ CallMicrophoneManager: class { enableMic = vi.fn(async () => {}) } }))
vi.mock('../../../frontend/src/voice/RemoteAvatar', () => ({
  bounded: (promise: Promise<unknown>) => promise,
  RemoteAvatar: class { unlock = vi.fn(async () => {}); connect = vi.fn(async () => {}); close = vi.fn(async () => {}); interrupt = vi.fn(); start = vi.fn(); chunk = vi.fn(); end = vi.fn() },
}))
import { SelectedVoiceTools } from '../../../frontend/src/voice/SelectedVoiceTools'

beforeEach(() => {
  mock.bots = []
  vi.stubGlobal('fetch', vi.fn(async (url: string) => new Response(JSON.stringify(url.endsWith('/prepare') ? { path: '/ws', max_seconds: 180, provider: 'anam' } : {}), { status: 200 })))
})
afterEach(async () => { cleanup(); await act(async () => {}); vi.unstubAllGlobals(); vi.clearAllMocks() })
async function connect() {
  const send = { current: null as ((text: string) => Promise<void>) | null }, ready = vi.fn()
  render(<SelectedVoiceTools sessionId="audit-no-real-session" name="Татьяна" profile="anam_tatiana" allowAudioFallback disabled={false} onConnection={() => {}} onReady={ready} sendRef={send} />)
  fireEvent.click(screen.getByRole('button', { name: 'Начать диалог' }))
  await waitFor(() => expect(ready).toHaveBeenCalledOnce())
  return { send, cb: mock.bots[0].options.callbacks }
}

test('reproduces a stale subtitle reappearing after a new typed reply', async () => {
  const { send, cb } = await connect()
  act(() => cb.onBotTtsText({ text: 'Первая старая фраза' }))
  expect(screen.getByText('Первая старая фраза')).toBeTruthy()
  await act(async () => { await send.current!('Перебиваю новым вопросом') })
  expect(screen.queryByText('Первая старая фраза')).toBeNull()
  act(() => cb.onBotTtsText({ text: 'ПОЗДНИЙ ТЕКСТ ОТМЕНЁННОГО ОТВЕТА' }))
  expect(screen.getByText('ПОЗДНИЙ ТЕКСТ ОТМЕНЁННОГО ОТВЕТА')).toBeTruthy()
})

test('reproduces stale subtitles after the VAD user-speaking interval ends', async () => {
  const { cb } = await connect()
  act(() => cb.onUserStartedSpeaking())
  act(() => cb.onBotTtsText({ text: 'Игнорируется пока пользователь говорит' }))
  expect(screen.queryByText('Игнорируется пока пользователь говорит')).toBeNull()
  act(() => cb.onUserStoppedSpeaking())
  act(() => cb.onBotTtsText({ text: 'ПОЗДНИЙ ТЕКСТ ПОСЛЕ ПАУЗЫ' }))
  expect(screen.getByText('ПОЗДНИЙ ТЕКСТ ПОСЛЕ ПАУЗЫ')).toBeTruthy()
})
