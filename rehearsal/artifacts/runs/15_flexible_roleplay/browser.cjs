// Isolated browser, synthetic transcript. API requests are intercepted; no tokens or media calls.
const { chromium } = require('playwright')
const fs = require('node:fs/promises')
const path = require('node:path')
const output = __dirname
const scenario = { id: 'ui-fixture', revision: 1, title: 'Обратная связь без конфликта', category: 'Управление', description: 'Обсудите с коллегой сорванный срок. Выясните причину и договоритесь о следующем шаге.', npc_name: 'Татьяна', npc_role: 'Коллега из вашей команды', employee_role: 'Руководитель', stages: [{ id: 'one', title: 'Выяснить причину', objective: 'Уточните, что помешало завершить работу.' }, { id: 'two', title: 'Договориться о решении', objective: 'Согласуйте следующий шаг.' }], criteria: [], status: 'published', duration_minutes: 6 }
scenario.situation = 'Второй раз отчёт от специалиста вашей команды поступил позже согласованного срока. Вы пригласили коллегу на разговор об этой ситуации. Причину задержки вам предстоит выяснить.'
scenario.stages.push({ id: 'three', title: 'Назначить проверку', objective: 'Определить срок.' })
const session = { progress_mode: 'flexible', stage_progress: [{ stage_id: 'two', quote: 'Предлагаю завтра', turn_id: 't0' }], id: 'ui-fixture', participant: 'Тест интерфейса', scenario, voice_mode: 'avatar', avatar_profile: 'anam_tatiana', allow_audio_fallback: true, mode: 'practice', is_demo: false, stage_index: 0, max_turns: 100, status: 'active', opening_message: 'Вы хотели обсудить отчёт? Я его уже отправила.', created_at: '2026-09-06T18:00:00Z', turns: Array.from({ length: 35 }, (_, i) => ({ id: `t${i}`, request_id: `r${i}`, user_text: `Давайте обсудим ситуацию ${i + 1}. Что помогло бы закончить отчёт вовремя?`, reply: 'Мне не хватило данных от другой команды. Предлагаю заранее договориться о сроке передачи материалов и оставить время на проверку.', stage_index: 0, status: 'committed', interrupted: false, created_at: '2026-09-06T18:00:00Z' })), report: null, report_status: 'none', report_error: '', completion_reason: '', review_note: '', reviewed: false }
async function main() {
  const browser = await chromium.launch({ headless: true, ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}) })
  const result = { viewports: [], text_viewports: [], browser_errors: [], unexpected_writes: [], external_requests: [] }
  let renderedSession = session
  try {
    const context = await browser.newContext({ reducedMotion: 'reduce' })
    const page = await context.newPage()
    page.on('pageerror', e => result.browser_errors.push(e.message))
    await page.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url())
      if (url.hostname !== '127.0.0.1') { result.external_requests.push(url.origin); return route.abort() }
      if (!url.pathname.startsWith('/api/text/')) return route.continue()
      if (request.method() !== 'GET') { result.unexpected_writes.push(url.pathname); return route.fulfill({ status: 403, json: { detail: 'UI fixture never calls real APIs' } }) }
      return route.fulfill({ json: url.pathname.includes('bootstrap') ? { scenarios: [scenario], sessions: [], runtime: { voice_mode: 'avatar', mode: 'practice', external_processing: true, is_demo: false } } : renderedSession })
    })
    for (const [width, height] of [[1440,900],[1280,720],[1024,768],[390,844],[667,375],[320,640],[390,420],[320,360]]) {
      await page.setViewportSize({ width, height })
      await page.goto('http://127.0.0.1:5176/#/session/ui-fixture')
      await page.getByRole('button', { name: 'Начать диалог', exact: true }).waitFor()
      await page.getByRole('textbox', { name: 'Ваша реплика' }).fill('Можно отправить текст и во время видеозвонка.')
      const measures = await page.evaluate(() => {
        const rect = selector => { const r = document.querySelector(selector).getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height, bottom: r.bottom, right: r.right } }
        const messages = document.querySelector('.messages')
        return { viewport: { width: innerWidth, height: innerHeight }, document: { width: document.documentElement.scrollWidth, height: document.documentElement.scrollHeight }, video: rect('.human-video'), chat: rect('.chat-panel'), input: rect('.composer'), start: rect('.call-start'), transcriptScroll: messages.scrollHeight > messages.clientHeight, transcriptHeight: messages.clientHeight }
      })
      measures.pass = measures.document.width <= width && measures.document.height <= height + 1 && measures.input.bottom <= height && measures.input.y >= 0 && measures.start.bottom <= height && measures.video.height > 0 && measures.transcriptScroll
      if (width >= 1000) measures.pass &&= measures.video.width > measures.chat.width
      await page.screenshot({ path: path.join(output, `call-${width}x${height}.png`) })
      await page.getByRole('button', { name: 'Задание', exact: true }).click()
      measures.planCount = await page.getByRole('navigation', { name: 'Краткий план разговора' }).getByRole('button').count()
      measures.pass &&= measures.planCount === 3
      measures.taskVisible = await page.getByRole('complementary', { name: 'Задание тренировки' }).isVisible()
      await page.keyboard.press('Escape')
      measures.taskClosed = await page.getByRole('complementary', { name: 'Задание тренировки' }).count() === 0
      await page.getByLabel('Параметры разговора', { exact: true }).click()
      measures.options = await page.locator('.call-options-panel').boundingBox()
      measures.pass &&= measures.options.y >= 0 && measures.options.x >= 0 && measures.options.x + measures.options.width <= width
      await page.keyboard.press('Escape')
      measures.optionsClosed = !(await page.locator('.call-options').evaluate(el => el.open))
      await page.getByLabel('Параметры разговора', { exact: true }).click()
      await page.getByRole('textbox', { name: 'Ваша реплика' }).click()
      measures.optionsClickAway = !(await page.locator('.call-options').evaluate(el => el.open))
      await page.getByRole('button', { name: 'Завершить', exact: true }).click()
      const report = page.getByRole('button', { name: 'Получить разбор' })
      await report.scrollIntoViewIfNeeded()
      measures.finishButton = await report.boundingBox()
      // scrollIntoView rounds scroll offsets to physical pixels; allow < 1 CSS pixel.
      measures.pass &&= measures.finishButton.y >= 0 && measures.finishButton.y + measures.finishButton.height <= height + 1
      await page.keyboard.press('Escape')
      measures.draftRestored = await page.getByRole('textbox', { name: 'Ваша реплика' }).inputValue() === 'Можно отправить текст и во время видеозвонка.'
      result.viewports.push(measures)
      await fs.writeFile(path.join(output, 'browser.json'), JSON.stringify(result, null, 2) + '\n')
    }
    renderedSession = { ...session, voice_mode: 'text', avatar_profile: undefined }
    for (const [width, height] of [[1440,900],[390,844]]) {
      await page.setViewportSize({ width, height })
      await page.reload()
      await page.locator('.conversation-layout.text-layout').waitFor()
      const measure = await page.evaluate(() => {
        const input = document.querySelector('.composer').getBoundingClientRect()
        return { width: innerWidth, height: innerHeight, documentHeight: document.documentElement.scrollHeight, documentWidth: document.documentElement.scrollWidth, inputBottom: input.bottom, inputTop: input.top }
      })
      measure.pass = measure.documentHeight <= height + 1 && measure.documentWidth <= width && measure.inputTop >= 0 && measure.inputBottom <= height
      result.text_viewports.push(measure)
      await page.screenshot({ path: path.join(output, `text-${width}x${height}.png`) })
    }
    renderedSession = { ...session, turns: [], scenario: { ...scenario, stages: Array.from({length: 8}, (_,i) => ({ id: 'g'+i, title: 'Пункт '+(i+1)+': уточнить исходные обстоятельства разговора', objective: 'Уточняющий вопрос' })) } }
    await page.setViewportSize({ width: 390, height: 844 })
    await page.reload()
    await page.getByRole('button', { name: 'Начать диалог', exact: true }).waitFor()
    const lastGoal = page.getByRole('navigation').getByRole('button').last()
    await lastGoal.scrollIntoViewIfNeeded()
    await lastGoal.click()
    result.long_plan = await page.getByRole('complementary', { name: 'Задание тренировки' }).isVisible()
    await page.keyboard.press('Escape')
    await page.screenshot({ path: path.join(output, 'long-plan-mobile.png') })
    result.passed = result.long_plan && result.viewports.every(v => v.pass && v.taskVisible && v.taskClosed && v.optionsClosed && v.optionsClickAway && v.draftRestored) && result.text_viewports.every(v => v.pass) && !result.browser_errors.length && !result.unexpected_writes.length
    await fs.writeFile(path.join(output, 'browser.json'), JSON.stringify(result, null, 2) + '\n')
    console.log(JSON.stringify({ passed: result.passed, call_viewports: result.viewports.map(v => ({ ...v.viewport, pass: v.pass })), text_viewports: result.text_viewports, browser_errors: result.browser_errors, unexpected_writes: result.unexpected_writes, external_requests: result.external_requests }, null, 2))
    if (!result.passed) process.exitCode = 1
  } finally { await browser.close() }
}
main().catch(e => { console.error(e); process.exitCode = 1 })
