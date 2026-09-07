const {chromium} = require('playwright');
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const base = 'http://127.0.0.1:8898';
const output = __dirname;
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

async function main() {
  const browser = await chromium.launch({headless:true, args:['--disable-gpu'], ...(process.env.CHROME_PATH ? {executablePath:process.env.CHROME_PATH} : {})});
  const result = {externalRequests:[], errors:[], viewports:[], checks:{}};
  try {
    const page = await browser.newPage({viewport:{width:1360,height:960}});
    page.on('pageerror', error => result.errors.push(error.message));
    await page.route('**/*', route => {
      if (new URL(route.request().url()).origin !== base) {result.externalRequests.push(route.request().url()); return route.abort();}
      return route.continue();
    });
    await page.goto(base);
    await page.waitForFunction(() => window.demoState?.phase === 'ready', null, {timeout:30000});
    await page.screenshot({path:path.join(output,'desktop.png'),fullPage:true});
    for (const voice of ['piper','silero']) {
      await page.locator('#voice').selectOption(voice);
      await page.locator('#speak').click();
      await page.waitForFunction(() => window.demoState.active, null, {timeout:60000});
      await pause(1100);
      const before = await page.evaluate(() => ({...window.demoState}));
      assert(before.audioDuration > 1);
      await page.screenshot({path:path.join(output,`speaking-${voice}.png`)});
      await page.locator('#stop').click();
      const after = await page.evaluate(() => ({...window.demoState}));
      assert.equal(after.active,false); assert.equal(after.mouth,0);
      assert.equal(await page.locator('#avatar').getAttribute('data-mouth'),'0');
      result.checks[voice] = {duration:before.audioDuration, cancel_handler_ms:after.cancelMs, neutral_mouth:true};
    }
    // Deliberately late response. Stop must fence it off, independent of ASR or TTS duration.
    await page.route('**/speak', async route => {
      const response = await route.fetch();
      await pause(1200);
      await route.fulfill({response}).catch(() => {});
    });
    await page.locator('#speak').click();
    await page.waitForFunction(() => window.demoState.phase === 'preparing');
    await page.locator('#stop').click();
    await pause(1600);
    assert.equal(await page.evaluate(() => window.demoState.active),false);
    assert.equal(await page.evaluate(() => window.demoState.mouth),0);
    result.checks.late_response_ignored = true;
    await page.unroute('**/speak');
    await page.locator('#text').fill(`Сегодня мы проверяем новую реплику. Мне важно понять ваше решение. Номер проверки ${Date.now() % 100000}.`);
    await page.locator('#voice').selectOption('piper');
    await page.locator('#speak').click();
    await page.waitForFunction(() => window.demoState.active, null, {timeout:60000});
    assert.notEqual(await page.locator('#latency').textContent(),'Из кэша');
    result.checks.new_text_plays = true;
    await page.locator('#text').fill('');
    await page.locator('#speak').click();
    assert.equal(await page.evaluate(() => window.demoState.active),false);
    result.checks.empty_input_stops_existing_playback = true;
    await page.getByRole('button',{name:'Клиент',exact:true}).click();
    for (const [width,height] of [[1360,960],[1280,720],[768,1024],[390,844],[320,640]]) {
      await page.setViewportSize({width,height});
      const dims = await page.evaluate(() => ({width:innerWidth, documentWidth:document.documentElement.scrollWidth,
        canvasWidth:document.querySelector('canvas').getBoundingClientRect().width}));
      assert(dims.documentWidth <= width);
      result.viewports.push({...dims,height,pass:true});
      if (width === 390) await page.screenshot({path:path.join(output,'mobile.png'),fullPage:true});
    }
    await page.emulateMedia({reducedMotion:'reduce'});
    await pause(100);
    assert.equal(await page.locator('#avatar').getAttribute('data-body'),'false');
    assert.equal(await page.locator('#avatar').getAttribute('data-pose'),'0.000');
    result.checks.reduced_motion = true;
    assert.equal(result.errors.length,0); assert.equal(result.externalRequests.length,0);
    result.pass = true;
  } finally {
    await fs.writeFile(path.join(output,'browser.json'),JSON.stringify(result,null,2)+'\n');
    await browser.close();
  }
  console.log(JSON.stringify(result,null,2));
}
main().catch(error => {console.error(error);process.exitCode=1;});
