import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.LIPSYNC_PLAYWRIGHT || '@playwright/test');
const root=path.resolve(process.argv[2]);
let reachable=false;
for(let i=0;i<60;i++){
 try{const r=await fetch('http://127.0.0.1:8897/manifest.json');if(r.ok){reachable=true;break;}}catch{}
 await new Promise(resolve=>setTimeout(resolve,500));
}
if(!reachable)throw Error('CPU lab did not become ready within 30 seconds');
const browser=await chromium.launch({headless:true,args:['--disable-gpu','--autoplay-policy=no-user-gesture-required']});
try{
 const page=await browser.newPage({viewport:{width:1150,height:850}});
 const errors=[],external=[];
 page.on('pageerror',e=>errors.push(e.message));
 page.on('request',r=>{if(!r.url().startsWith('http://127.0.0.1:8897/')&&!r.url().startsWith('data:'))external.push(r.url());});
 await page.goto('http://127.0.0.1:8897/');
 await page.waitForFunction(()=>!document.getElementById('speak').disabled,{},{timeout:30000});
 await page.locator('#text').fill('Добрый день! Я проверяю совершенно новую фразу и возможность остановить её в любой момент.');
 await page.locator('#speak').click();
 await page.waitForFunction(()=>window.labState.active,{},{timeout:30000});
 const before=await page.evaluate(()=>({frames:window.labState.frames,time:performance.now()}));
 await page.waitForTimeout(1400);
 const running=await page.evaluate(()=>({...window.labState,time:performance.now()}));
 await page.screenshot({path:path.join(root,'browser_desktop.png'),fullPage:true});
 await page.locator('#stop').click();
 const stopped=await page.evaluate(()=>({...window.labState}));
 await page.waitForTimeout(400);
 const stable=await page.evaluate(()=>({...window.labState}));
 if(stopped.active||stopped.mouth!==0||stable.active||stable.mouth!==0)throw Error('Playback resumed after cancellation');
 await page.locator('#speak').click();await page.locator('#stop').click();
 await page.waitForTimeout(1800);
 const preparingCancel=await page.evaluate(()=>({...window.labState}));
 if(preparingCancel.active)throw Error('Cancelled pending speech started');
 await page.locator('#text').fill('Новая попытка после прерывания работает.');await page.locator('#speak').click();
 await page.waitForFunction(()=>window.labState.active,{},{timeout:30000});
 await page.locator('#stop').click();
 await page.setViewportSize({width:390,height:844});
 const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
 await page.screenshot({path:path.join(root,'browser_mobile.png'),fullPage:true});
 const sorted=running.drawMs.slice().sort((a,b)=>a-b);
 const result={browser_gpu_disabled:true,measured_fps:(running.frames-before.frames)/(running.time-before.time)*1000,
   draw_ms_p95:sorted[Math.floor(sorted.length*.95)],cancel_handler_ms:stopped.cancelMs,
   cancellation_stopped_audio_and_mouth:!stopped.active&&stopped.mouth===0,
   stale_preparation_did_not_resume:!preparingCancel.active,new_phrase_after_cancel:true,
   idle_body_continues:stable.frames>stopped.frames,mobile_overflow:overflow,errors,external_requests:external};
 await fs.writeFile(path.join(root,'browser_metrics.json'),JSON.stringify(result,null,2));console.log(result);
 if(errors.length||external.length||overflow)process.exitCode=1;
}finally{await browser.close();}
