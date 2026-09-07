// Behaviour clock only. Speech frame selection always uses the audio clock.
export class MotionClock {
  constructor(count){this.count=count;this.travel=0;this.speed=.22;this.last=null;this.restSpeed=.22;}
  update(now,speaking){
    const dt=this.last===null?0:Math.max(0,Math.min(.1,(now-this.last)/1000));this.last=now;
    const target=speaking?Math.max(.42,this.restSpeed):this.restSpeed;
    this.speed+=(target-this.speed)*(1-Math.exp(-dt/.65));
    this.travel+=dt*25*this.speed;
    // Cosine turnaround has zero speed at the endpoints; no abrupt reversal.
    return (this.count-1)*(.5-.5*Math.cos(Math.PI*this.travel/Math.max(1,this.count-1)));
  }
}

export function correctionTable(rects){
  const centres=rects.map(r=>[(r[0]+r[2])/2,(r[1]+r[3])/2]);
  return centres.map((c,i)=>{
    const sum=[0,0];let weight=0;
    for(let d=-6;d<=6;d++){const j=Math.max(0,Math.min(centres.length-1,i+d)),w=Math.exp(-d*d/12.5);weight+=w;sum[0]+=w*centres[j][0];sum[1]+=w*centres[j][1];}
    return sum.map((v,j)=>Math.max(-3,Math.min(3,v/weight-c[j])));
  });
}

export function bodyRow(y,height,time,amount){
  const q=y/height,torso=Math.exp(-Math.pow((q-.70)/.24,2));
  const breathe=Math.sin(2*Math.PI*time/4.9);
  // Small analytic deformation, not generated arms/gestures or a camera zoom.
  return {x:amount*(1-q*q)*(2.1*Math.sin(2*Math.PI*time/13)+.5*Math.sin(2*Math.PI*time/7.3)),
    y:-amount*1.1*breathe*torso,scale:1+amount*.009*breathe*torso};
}

export class MotionRenderer {
  constructor(canvas,meta,assets){
    this.canvas=canvas;this.ctx=canvas.getContext('2d',{willReadFrequently:true});this.meta=meta;this.assets=assets;
    this.corrections=correctionTable(meta.rects);this.cache=new Map();
    this.mix=document.createElement('canvas');this.mix.width=canvas.width;this.mix.height=canvas.height;this.mixCtx=this.mix.getContext('2d');
  }
  composed(p,k){
    const key=p+':'+k;
    if(this.cache.has(key))return this.cache.get(key);
    const c=document.createElement('canvas');c.width=this.canvas.width;c.height=this.canvas.height;const x=c.getContext('2d');
    const a=this.assets[p],r=this.meta.rects[p];x.drawImage(a.base,0,0);
    x.drawImage(a.sheet,(k%8)*128,Math.floor(k/8)*128,128,128,r[0],r[1],r[2]-r[0],r[3]-r[1]);
    this.cache.set(key,c);while(this.cache.size>8)this.cache.delete(this.cache.keys().next().value);return c;
  }
  render(position,k,time,{body=true,legacy=false}={}){
    const w=this.canvas.width,h=this.canvas.height,lo=Math.floor(position),hi=Math.min(this.meta.poses-1,lo+1),a=position-lo;
    const x=this.mixCtx;x.globalAlpha=1;x.clearRect(0,0,w,h);
    for(const [p,alpha] of [[lo,1],[hi,a]]){
      if(alpha===0)continue;const offset=legacy?[0,0]:this.corrections[p];x.globalAlpha=alpha;
      // Slight overscan hides the <=3px stabilisation boundary, not a breathing zoom.
      x.drawImage(this.composed(p,k),-4+offset[0],-4+offset[1],w+8,h+8);
    }
    x.globalAlpha=1;this.ctx.drawImage(this.mix,0,0);
    if(body&&!legacy){
      for(let y=0;y<h;y+=6){const rows=Math.min(7,h-y),m=bodyRow(y,h,time,1);
        this.ctx.drawImage(this.mix,0,y,w,rows,m.x-(m.scale-1)*w/2,y+m.y,w*m.scale,rows+.5);}
    }
    this.canvas.dataset.pose=position.toFixed(3);this.canvas.dataset.mouth=String(k);
    this.canvas.dataset.body=String(body&&!legacy);
  }
}
