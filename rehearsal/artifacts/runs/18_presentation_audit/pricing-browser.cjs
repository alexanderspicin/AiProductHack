// Public pricing pages only; isolated browser, no account cookies or purchases.
const {chromium} = require('playwright');
const fs = require('node:fs/promises');
const path = require('node:path');
const out = path.resolve('artifacts/private/18_presentation_audit');
async function main() {
  const browser = await chromium.launch({headless:true, executablePath:process.env.CHROME_PATH});
  try {
    for (const [name,url] of [['anam','https://anam.ai/pricing'], ['tavus','https://www.tavus.io/pricing'], ['cartesia','https://www.cartesia.ai/pricing']]) {
      const page = await browser.newPage({viewport:{width:1440,height:1100}});
      await page.goto(url, {waitUntil:'domcontentloaded',timeout:45000});
      await page.waitForTimeout(3500);
      await page.screenshot({path:path.join(out,`pricing-${name}.png`),fullPage:false});
      await fs.writeFile(path.join(out,`pricing-${name}.txt`),await page.locator('body').innerText());
      console.log(name, 'captured public page');
      await page.close();
    }
  } finally { await browser.close(); }
}
main().catch(e=>{console.error(e.message);process.exitCode=1});
