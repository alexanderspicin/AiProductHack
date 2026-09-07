import assert from 'node:assert/strict';
import fs from 'node:fs';
import {MotionClock,bodyRow,correctionTable} from '../07_avatar_graph/motion.js';
const idle=new MotionClock(100),speech=new MotionClock(100),positions=[];
for(let i=0;i<=60*40;i++){const t=i*1000/60;positions.push(idle.update(t,false));speech.update(t,true);}
assert(Math.abs(idle.speed-.22)<1e-9);assert(Math.abs(speech.speed-.42)<1e-4);
assert(positions.every(x=>x>=0&&x<=99));
const steps=positions.slice(1).map((x,i)=>Math.abs(x-positions[i]));
const legacy=positions.map((_,i)=>{const k=Math.floor(i*25/60)%198;return k<100?k:198-k;});
const peakSecondDifference=xs=>Math.max(...xs.slice(2).map((x,i)=>Math.abs(x-2*xs[i+1]+xs[i])));
assert(peakSecondDifference(positions)<peakSecondDifference(legacy));
assert(Math.max(...steps)<.16,'Idle pose movement should remain small per display frame');
const at=idle.travel;idle.update(1000000,false);assert(idle.travel-at<1,'No huge resume jump');
const fixed=new MotionClock(1);assert.equal(fixed.update(1000,true),0);
for(let y=0;y<=540;y+=6){const row=bodyRow(y,540,1.2,0);assert.deepEqual(row,{x:0,y:-0,scale:1});}
const rects=Array.from({length:100},(_,i)=>[100+(i%2),200,180+(i%2),280]);
assert(correctionTable(rects).every(x=>x.every(v=>Number.isFinite(v)&&Math.abs(v)<=3)));
const result={measurement:'deterministic pose-index trajectory, not physical head acceleration or a human rating',idle_speed:.22,speech_speed:.42,max_idle_pose_step_at_60fps:Math.max(...steps),smooth_peak_second_difference:peakSecondDifference(positions),legacy_peak_second_difference:peakSecondDifference(legacy),bounded_resume:true,single_pose:true,body_disable:true,correction_bounded:true};
console.log(result);fs.writeFileSync(new URL('./motion_metrics.json',import.meta.url),JSON.stringify(result,null,2));
