// Deterministic export of example 1. Same MotionRenderer; local assets only.
const {chromium} = require('playwright');
const fs = require('node:fs/promises');
const path = require('node:path');
const {spawn, execFileSync} = require('node:child_process');
const {once} = require('node:events');
const base = 'http://127.0.0.1:8898';
const root = path.resolve(__dirname, '../../..');
const out = path.join(root, 'artifacts/private/17_offline_defense');
const text = 'Понимаю ваши сомнения. Я уже пробовал похожее решение, но результата не получил. Чем ваш подход отличается?';

async function main() {
  const started = Date.now();
  await fs.mkdir(out, {recursive:true});
  const response = await fetch(base+'/speak', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({voice:'piper',text})});
  const speech = await response.json();
  if (!response.ok) throw Error(speech.error);
  const wavResponse = await fetch(base+speech.audio);
  if (!wavResponse.ok) throw Error('Local WAV unavailable');
  const wav = path.join(out,'example-1-piper.wav');
  await fs.writeFile(wav,Buffer.from(await wavResponse.arrayBuffer()));
  const video = path.join(out,'example-1-piper.mp4');
  // Do not silently overwrite a delivered video on subsequent runs.
  try {await fs.access(video); throw Error('Video already exists; rename it before exporting again');}
  catch (error) {if (error.code !== 'ENOENT') throw error;}
  const browser = await chromium.launch({headless:true,args:['--disable-gpu'],...(process.env.CHROME_PATH ? {executablePath:process.env.CHROME_PATH} : {})});
  let encoder;
  let stderr = '';
  const external = [];
  try {
    const page = await browser.newPage();
    await page.route('**/*', route => {
      const url = new URL(route.request().url());
      if (url.origin !== base) {external.push(url.origin);return route.abort();}
      if (url.pathname === '/') return route.fulfill({contentType:'text/html',body:'<!doctype html><meta charset="utf-8"><canvas id="face"></canvas>'});
      return route.continue();
    });
    await page.goto(base);
    const size = await page.evaluate(async () => {
      const {MotionRenderer,MotionClock} = await import('/motion.js');
      const meta = await (await fetch('/manifest.json')).json();
      const canvas = document.getElementById('face');
      [canvas.width,canvas.height] = meta.size;
      const assets = [];
      let next=0;
      async function image(url) {const im=new Image();im.src=url;await im.decode();return im;}
      await Promise.all(Array.from({length:4},async () => {
        while(next<meta.poses) {
          const p=next++, id=String(p).padStart(3,'0');
          const [base,sheet]=await Promise.all([image(`/assets/base/${id}.jpg`),image(`/assets/atlas/${id}.png`)]);
          assets[p]={base,sheet};
        }
      }));
      window.exporter={canvas,renderer:new MotionRenderer(canvas,meta,assets),clock:new MotionClock(meta.poses)};
      return meta.size;
    });
    const fps=25;
    encoder=spawn('ffmpeg',['-v','error','-n','-f','image2pipe','-framerate',String(fps),'-i','pipe:0','-i',wav,
      '-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-b:a','128k',
      '-shortest','-movflags','+faststart',video],{stdio:['pipe','ignore','pipe']});
    const completed=once(encoder,'close');
    encoder.stderr.on('data',data=>{stderr+=data.toString();});
    for(let frame=0;frame<speech.states.length;frame++) {
      const png=await page.evaluate(({frame,mouth,fps})=>{
        const {canvas,renderer,clock}=window.exporter;
        const time=frame/fps,position=clock.update(time*1000,true);
        renderer.render(position,mouth,time,{body:true});
        const c=canvas.getContext('2d');
        c.fillStyle='rgba(22,29,25,.88)';c.fillRect(0,canvas.height-40,canvas.width,40);
        c.fillStyle='#ffffff';c.font='11px sans-serif';
        c.fillText('AI-аватар · Piper · локальный синтез',10,canvas.height-24);
        c.fillText('Демонстрационный образ DH Live',10,canvas.height-9);
        return canvas.toDataURL('image/png').split(',')[1];
      },{frame,mouth:speech.states[frame],fps});
      if(!encoder.stdin.write(Buffer.from(png,'base64'))) await once(encoder.stdin,'drain');
    }
    encoder.stdin.end();
    const [code]=await completed;
    if(code) throw Error('ffmpeg failed: '+stderr);
    execFileSync('ffmpeg',['-v','error','-i',video,'-f','null','-'],{stdio:'pipe'});
    const media=JSON.parse(execFileSync('ffprobe',['-v','error','-show_streams','-show_format','-of','json',video],{encoding:'utf8'}));
    const v=media.streams.find(s=>s.codec_type==='video'),a=media.streams.find(s=>s.codec_type==='audio');
    if(!v||!a||Math.abs(Number(v.duration)-Number(a.duration))>.1) throw Error('Invalid video/audio duration');
    const report={date:'2026-09-07',example:1,text,voice:'piper',cached_tts:speech.cached,
      output:path.relative(root,video),source_size:size,fps,frames:speech.states.length,
      video_seconds:Number(v.duration),audio_seconds:Number(a.duration),video_codec:v.codec_name,audio_codec:a.codec_name,
      bytes:(await fs.stat(video)).size,total_export_s:(Date.now()-started)/1000,external_requests:external,api_cost_rub:0,decode_ok:true};
    await fs.writeFile(path.join(__dirname,'export_video.json'),JSON.stringify(report,null,2)+'\n');
    console.log(JSON.stringify(report,null,2));
  } finally {
    if(encoder && encoder.exitCode===null) encoder.kill('SIGTERM');
    await browser.close();
  }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
