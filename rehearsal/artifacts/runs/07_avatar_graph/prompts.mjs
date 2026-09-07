// Offline geometry prompts using the compatible upstream WebGL shaders.
// No neural image inference here. The H100 teacher consumes these RGBA maps.
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.LIPSYNC_PLAYWRIGHT || '@playwright/test');
const root=path.resolve(process.argv[2]);
const inputs=JSON.parse(await fs.readFile(path.join(root,'inputs/web_inputs.json'),'utf8'));
const original=await fs.readFile(path.join(root,'teacher_source/web_demo/static/js/MiniLive2.js'),'utf8');
const vertex=original.match(/const vertexShaderSource = `([\s\S]*?)`;/)[1];
const fragment=original.match(/const fragmentShaderSource = `([\s\S]*?)`;/)[1];
const texture='data:image/png;base64,'+(await fs.readFile(path.join(root,'teacher_source/mini_live/bs_texture_halfFace.png'))).toString('base64');
const browser=await chromium.launch({headless:true,args:process.platform==='darwin'?['--use-angle=metal']:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try {
 const page=await browser.newPage();
 const info=await page.evaluate(async ({vertex,fragment,texture,inputs})=>{
  const canvas=document.createElement('canvas'); canvas.width=128;canvas.height=128;
  const gl=canvas.getContext('webgl2',{antialias:false,preserveDrawingBuffer:true});
  if(!gl) throw Error('WebGL2 unavailable');
  const program=gl.createProgram();
  for(const [type,source] of [[gl.VERTEX_SHADER,vertex],[gl.FRAGMENT_SHADER,fragment]]) {
   const shader=gl.createShader(type);gl.shaderSource(shader,source);gl.compileShader(shader);
   if(!gl.getShaderParameter(shader,gl.COMPILE_STATUS)) throw Error(gl.getShaderInfoLog(shader));
   gl.attachShader(program,shader);
  }
  gl.linkProgram(program);if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(program));
  gl.useProgram(program);
  const verts=[],faces=[];
  for(const line of inputs.face3D_obj) {
   const parts=line.trim().split(/\s+/);
   if(parts[0]==='v')verts.push(...parts.slice(1).map(Number));
   if(parts[0]==='f')faces.push(...parts.slice(1).map(x=>Number(x.split('/')[0])-1));
  }
  gl.bindBuffer(gl.ARRAY_BUFFER,gl.createBuffer());gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(verts),gl.STATIC_DRAW);
  gl.enableVertexAttribArray(0);gl.vertexAttribPointer(0,3,gl.FLOAT,false,20,0);
  gl.enableVertexAttribArray(1);gl.vertexAttribPointer(1,2,gl.FLOAT,false,20,12);
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,gl.createBuffer());gl.bufferData(gl.ELEMENT_ARRAY_BUFFER,new Uint16Array(faces),gl.STATIC_DRAW);
  const img=new Image();img.src=texture;await img.decode();
  gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,gl.createTexture());
  gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,img);
  for(const p of [gl.TEXTURE_WRAP_S,gl.TEXTURE_WRAP_T])gl.texParameteri(gl.TEXTURE_2D,p,gl.CLAMP_TO_EDGE);
  for(const p of [gl.TEXTURE_MIN_FILTER,gl.TEXTURE_MAG_FILTER])gl.texParameteri(gl.TEXTURE_2D,p,gl.LINEAR);
  gl.uniform1i(gl.getUniformLocation(program,'texture_bs'),0);
  gl.uniformMatrix4fv(gl.getUniformLocation(program,'gProjection'),false,new Float32Array([1/64,0,0,0,0,1/64,0,0,0,0,.001,0,-1,-1,0,1]));
  gl.enable(gl.DEPTH_TEST);gl.enable(gl.BLEND);gl.blendFunc(gl.SRC_ALPHA,gl.ONE_MINUS_SRC_ALPHA);
  gl.enable(gl.CULL_FACE);gl.cullFace(gl.BACK);gl.frontFace(gl.CW);gl.viewport(0,0,128,128);
  window.renderJobs=(jobs)=>{
   const output=new Uint8Array(jobs.length*128*128*4);
   for(let j=0;j<jobs.length;j++){
    const [pose,bs]=jobs[j];const p=inputs.poses[pose].points;
    gl.uniformMatrix4fv(gl.getUniformLocation(program,'gWorld0'),false,new Float32Array(p.slice(0,16)));
    gl.uniform2fv(gl.getUniformLocation(program,'vertBuffer'),new Float32Array(p.slice(16)));
    const b=new Float32Array(12);b.set(bs);
    gl.uniform1fv(gl.getUniformLocation(program,'bsVec'),b);
    gl.clearColor(.5,.5,.5,0);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
    gl.drawElements(gl.TRIANGLES,faces.length,gl.UNSIGNED_SHORT,0);
    gl.readPixels(0,0,128,128,gl.RGBA,gl.UNSIGNED_BYTE,output.subarray(j*65536,(j+1)*65536));
   }
   if(gl.getError()!==gl.NO_ERROR)throw Error('WebGL render error');
   let str='';for(let i=0;i<output.length;i+=16384)str+=String.fromCharCode(...output.subarray(i,i+16384));
   return btoa(str);
  };
  const ext=gl.getExtension('WEBGL_debug_renderer_info');
  return {renderer:ext?gl.getParameter(ext.UNMASKED_RENDERER_WEBGL):'unavailable',vertices:verts.length/5,triangles:faces.length/3};
 },{vertex,fragment,texture,inputs});
 const dest=path.join(root,'inputs/prompts');await fs.mkdir(dest,{recursive:true});
 const start=Date.now();
 for(let p=0;p<inputs.poses.length;p++){
  const file=path.join(dest,`atlas_${String(p).padStart(3,'0')}.bin`);
  // Regenerate after every preparation. A new codebook invalidates all old maps.
  const b64=await page.evaluate(j=>window.renderJobs(j),inputs.codebook.map(bs=>[p,bs]));
  await fs.writeFile(file,Buffer.from(b64,'base64'));
  if(p%20===0)console.log('pose',p);
 }
 const phase=i=>{const n=inputs.poses.length;if(n<2)return 0;const p=i%(2*n-2);return p<n?p:2*n-2-p;};
 for(const [name,controls] of Object.entries(inputs.heldout)){
  const chunks=[];
  for(let i=0;i<controls.length;i+=32){
   const b64=await page.evaluate(j=>window.renderJobs(j),controls.slice(i,i+32).map((bs,j)=>[phase(i+j),bs]));
   chunks.push(Buffer.from(b64,'base64'));
  }
  await fs.writeFile(path.join(dest,`${name}.bin`),Buffer.concat(chunks));
 }
 const metrics={...info,seconds:(Date.now()-start)/1000};
 await fs.writeFile(path.join(root,'inputs/prompt_metrics.json'),JSON.stringify(metrics,null,2));
 console.log(metrics);
} finally {await browser.close();}
