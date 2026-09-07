import { StrictMode } from 'react'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

const mocks = vi.hoisted(() => ({ options: null as any, api: vi.fn(),
  disconnect: vi.fn(), sendText: vi.fn(), enableMic: vi.fn(), sendClientMessage: vi.fn() }))
vi.mock('../src/text/api', () => ({ api: mocks.api }))
vi.mock('../src/avatar/AvatarStage', () => ({ AvatarStage: () => <div>3D-сцена</div> }))
vi.mock('@pipecat-ai/websocket-transport', () => ({ WebSocketTransport: class {} }))
vi.mock('@pipecat-ai/client-js', () => ({ PipecatClient: class {
  constructor(options: any) { mocks.options = options }
  initDevices = async () => {}
  connect = async () => { mocks.options.callbacks.onBotReady() }
  disconnect = mocks.disconnect
  sendText = mocks.sendText
  enableMic = mocks.enableMic
  sendClientMessage = mocks.sendClientMessage
} }))
import { VoiceTools } from '../src/voice/VoiceTools'

function mount() {
  const sendRef = { current: null as null | ((text: string) => Promise<void>) }
  const stopRef = { current: null as null | (() => Promise<void>) }
  const onConnection = vi.fn()
  render(<StrictMode><VoiceTools sessionId="test" name="Елена" disabled={false}
    onConnection={onConnection} onReady={vi.fn()} onEnd={vi.fn()} sendRef={sendRef} stopRef={stopRef} /></StrictMode>)
  return { sendRef, stopRef, onConnection }
}
async function connect() {
  fireEvent.click(screen.getByRole('button', { name: 'Начать диалог' }))
  await screen.findByText('Слушаю вас')
}
beforeEach(() => {
  vi.clearAllMocks()
  mocks.api.mockImplementation(async (path: string) => path.endsWith('/prepare') ? { path: '/api/text/sessions/test/voice/ws' } : { stopped: true })
  mocks.disconnect.mockResolvedValue(undefined)
  mocks.sendText.mockResolvedValue(undefined)
  mocks.enableMic.mockResolvedValue(undefined)
})
afterEach(cleanup)

test('avatar preview does not open a paid session or request microphone devices', () => {
  mount()
  fireEvent.click(screen.getByRole('button', { name: 'Посмотреть персонажа без микрофона' }))
  expect(screen.getByRole('button', { name: 'Вернуться к вводной' })).toBeTruthy()
  expect(mocks.api).not.toHaveBeenCalled()
})

test('StrictMode preserves stop handle; text uses the same Pipecat session', async () => {
  const { sendRef, stopRef, onConnection } = mount()
  expect(stopRef.current).toBeTypeOf('function')
  await connect()
  expect(mocks.options.enableMic).toBe(true)
  expect(mocks.options.enableCam).toBe(false)
  await act(async () => { await sendRef.current?.('На каком шаге ошибка?') })
  expect(mocks.sendText).toHaveBeenCalledWith('На каком шаге ошибка?', { run_immediately: true, audio_response: true })
  await act(async () => { await stopRef.current?.() })
  expect(mocks.disconnect).toHaveBeenCalledOnce()
  expect(mocks.api).toHaveBeenCalledWith('/sessions/test/voice/stop', 'POST')
  expect(sendRef.current).toBeNull()
  expect(onConnection).toHaveBeenLastCalledWith(false)
})

test('manual interruption clears captions and ignores late words until the next utterance', async () => {
  mount(); await connect()
  const callbacks = mocks.options.callbacks
  act(() => {
    callbacks.onServerMessage({ type: 'playback_start', utterance_id: 1, t: 0 })
    callbacks.onBotStartedSpeaking()
    callbacks.onBotTtsText({ text: 'Здравствуйте' })
  })
  expect(screen.getByLabelText('Субтитры собеседника').textContent).toBe('Здравствуйте')
  fireEvent.click(screen.getByRole('button', { name: 'Перебить' }))
  expect(mocks.sendClientMessage).toHaveBeenCalledWith('interrupt')
  act(() => { callbacks.onBotTtsText({ text: 'устаревшие слова' }) })
  expect(screen.queryByLabelText('Субтитры собеседника')).toBeNull()
  act(() => {
    callbacks.onServerMessage({ type: 'playback_start', utterance_id: 2, t: 0 })
    callbacks.onBotTtsText({ text: 'Слушаю' })
  })
  expect(screen.getByLabelText('Субтитры собеседника').textContent).toBe('Слушаю')
})

test('mute goes through Pipecat; failed cleanup blocks a fresh paid session until retried', async () => {
  const { onConnection } = mount(); await connect()
  fireEvent.click(screen.getByRole('button', { name: 'Выключить микрофон' }))
  await screen.findByRole('button', { name: 'Включить микрофон' })
  expect(mocks.enableMic).toHaveBeenCalledWith(false)
  mocks.api.mockRejectedValueOnce(new Error('Нет подтверждения остановки'))
  fireEvent.click(screen.getByRole('button', { name: 'Приостановить' }))
  await screen.findByRole('button', { name: 'Повторить отключение' })
  expect(screen.queryByRole('button', { name: 'Начать диалог' })).toBeNull()
  expect(onConnection).toHaveBeenLastCalledWith(true)
  fireEvent.click(screen.getByRole('button', { name: 'Повторить отключение' }))
  await waitFor(() => expect(screen.getByRole('button', { name: 'Начать диалог' })).toBeTruthy())
  expect(onConnection).toHaveBeenLastCalledWith(false)
})
