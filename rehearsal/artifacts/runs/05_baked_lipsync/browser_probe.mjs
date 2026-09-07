// Existing Playwright install, passed explicitly to avoid modifying app dependencies.
import {createRequire} from 'node:module';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.LIPSYNC_PLAYWRIGHT||'@playwright/test');
const here=path.dirname(fileURLToPath(import.meta.url));
const output=path.resolve(here,'../../private/05_baked_lipsync');
const browser=await chromium.launch({headless:true,args:['--autoplay-policy=no-user-gesture-required','--use-angle=metal']});
const context=await browser.newContext({viewport:{width:1220,height:1000}});
const page=await context.newPage();
const errors=[],dialogs=[],requests=[];
page.on('pageerror',e=>errors.push(e.message));
page.on('dialog',async d=>{dialogs.push(d.message());await d.dismiss()});
await context.route('**/*',async route=>{const u=new URL(route.request().url());if(u.hostname!=='127.0.0.1'){requests.push(u.origin);return route.abort()}return route.continue()});
const results={errors,dialogs,blocked_external_requests:requests,browser:browser.version(),variants:[]};
try{
 await page.goto('http://127.0.0.1:8896');
 await page.waitForFunction(()=>window.lab?.ready,{timeout:20000});
 await page.screenshot({path:path.join(output,'lab_desktop.png'),fullPage:true});
 for(const variant of ['energy','model','neural']){
  await page.locator(`input[value="${variant}"]`).check();
  await page.selectOption('#phrase','2');
  if(variant==='neural')await page.waitForFunction(()=>document.getElementById('neural').contentWindow.labDH?.ready,null,{timeout:20000});
  await page.click('#play');
  await page.waitForFunction(()=>window.lab.speaking,null,{timeout:15000});
  await page.waitForTimeout(3200);
  await page.screenshot({path:path.join(output,`lab_${variant}.png`),fullPage:true});
  const metrics=await page.evaluate(mode=>{
   const percentile=(a,q)=>{const s=[...a].sort((a,b)=>a-b);return s[Math.floor((s.length-1)*q)]};
   let frames,draw,wasm,renderer,audioPrepMs;
   if(mode==='neural'){const d=document.getElementById('neural').contentWindow.labDH;frames=d.frames.map(f=>f.time);draw=d.frames.map(f=>f.ms);wasm=d.wasmMs;renderer=d.renderer;audioPrepMs=d.lastAudioPrepMs}
   else{frames=window.lab.frames;draw=window.lab.drawMs}
   return {frame_count:frames.length,observed_fps:1000*(frames.length-1)/(frames.at(-1)-frames[0]),draw_median_ms:percentile(draw,.5),draw_p95_ms:percentile(draw,.95),wasm_median_ms:wasm?percentile(wasm,.5):null,audio_prep_ms:audioPrepMs,renderer:renderer||'Canvas2D; acceleration unspecified'};
  },variant);
  const stopped=await page.evaluate(()=>{const t=performance.now();window.lab.stop();return {handler_ms:performance.now()-t,active_sources:window.lab.activeSources,speaking:window.lab.speaking,mouth:window.lab.mouth}});
  await page.waitForTimeout(300);
  const after=await page.evaluate(()=>({speaking:window.lab.speaking,active_sources:window.lab.activeSources,mouth:window.lab.mouth}));
  results.variants.push({variant,...metrics,interruption:stopped,after_300ms:after});
  if(metrics.frame_count<30)throw Error(`${variant}: animation is not producing frames`);
  if(after.speaking||after.active_sources!==0)throw Error(`${variant}: stale playback after interruption`);
 }
 // A new phrase was not part of the prepared manifest; requires local TTS + CPU model.
 await page.locator('input[value="model"]').check();
 await page.fill('#text','Сегодня мы проверяем новую фразу. Пожалуйста, попробуйте перебить меня.');
 await page.click('#play');await page.waitForFunction(()=>window.lab.speaking,null,{timeout:20000});
 results.unseen_text_status=await page.locator('#status').textContent();
 await page.click('#stop');
 // Cancellation while the async response is pending must not restart playback.
 await page.fill('#text','Эта фраза отменяется во время подготовки и не должна прозвучать.');
 await page.click('#play');await page.click('#stop');await page.waitForTimeout(3500);
 results.cancel_during_prepare=await page.evaluate(()=>({speaking:window.lab.speaking,sources:window.lab.activeSources,status:document.getElementById('status').textContent}));
 await page.setViewportSize({width:390,height:844});
 await page.screenshot({path:path.join(output,'lab_mobile.png'),fullPage:true});
 results.mobile_no_overflow=await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth);
}catch(e){results.failure=e.message;process.exitCode=1}
finally{await fs.writeFile(path.join(here,'browser_metrics.json'),JSON.stringify(results,null,2));console.log(JSON.stringify(results,null,2));await browser.close()}
