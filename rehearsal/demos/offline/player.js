import {MotionClock, MotionRenderer} from '/motion.js';

const $ = id => document.getElementById(id);
const examples = {
  dialogue: 'Понимаю ваши сомнения. Я уже пробовал похожее решение, но результата не получил. Чем ваш подход отличается?',
  lips: 'Павел, мы попробуем поменять план. В понедельник обсудим бюджет, а потом выберем подходящий вариант.',
  intonation: 'Вы серьёзно? Мне обещали доставку вчера! Хорошо, я готов подождать. Но назовите, пожалуйста, точную дату.',
};
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
let ready = false, voices = [], manifest, renderer, motion, assets = [];
let audioContext, source = null, controller = null, generation = 0, states = [], audioStart = 0;
let position = 0, epoch = performance.now(), lastFrame = -1;
// Diagnostic state contains no user text. Used by the local smoke test.
window.demoState = {phase: 'loading', active: false, generation: 0, mouth: 0, cancelMs: 0, frames: 0};

function setPhase(phase, message, error = false) {
  window.demoState.phase = phase;
  $('status').textContent = message;
  $('status').classList.toggle('error', error);
  $('stage-state').textContent = {loading:'Загрузка', ready:'Готов', preparing:'Готовит речь', speaking:'Говорит', stopped:'Остановлен', error:'Ошибка'}[phase];
  $('stop').disabled = !['preparing','speaking'].includes(phase);
  $('speak').disabled = !ready || phase === 'preparing' || !voices.find(v => v.id === $('voice').value)?.available;
}
function draw(mouth = 0) {
  renderer?.render(position, mouth, (performance.now() - epoch) / 1000, {body: !reducedMotion.matches});
  window.demoState.mouth = mouth;
  window.demoState.frames++;
}
function stop(message = 'Остановлено. Запоздалый ответ не начнёт воспроизведение.') {
  const started = performance.now();
  generation++;
  controller?.abort(); controller = null;
  if (source) {
    source.onended = null;
    try { source.stop(); } catch { /* May have already ended. */ }
    source.disconnect(); source = null;
  }
  states = [];
  window.demoState.active = false;
  window.demoState.generation = generation;
  draw(0);
  window.demoState.cancelMs = performance.now() - started;
  setPhase('stopped', message);
}
async function speak() {
  const text = $('text').value.trim();
  if (!ready) return;
  stop();
  if (!text) { $('text').focus(); setPhase('ready', 'Введите фразу для озвучивания.', true); return; }
  const token = generation;
  setPhase('preparing', 'Создаю локальный голос и движения. В первый раз модель может загружаться дольше.');
  const currentController = new AbortController(); controller = currentController;
  try {
    audioContext ||= new AudioContext();
    await audioContext.resume();
    if (token !== generation) return;
    const response = await fetch('/speak', {method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({text, voice:$('voice').value}), signal:currentController.signal});
    const data = await response.json();
    if (token !== generation) return;
    if (!response.ok) throw Error(data.error || 'Локальный сервер недоступен');
    const wav = await fetch(data.audio, {signal:currentController.signal});
    if (!wav.ok) throw Error('Не удалось загрузить локальный звук. Нажмите «Произнести» ещё раз.');
    const audio = await audioContext.decodeAudioData(await wav.arrayBuffer());
    if (token !== generation) return;
    states = data.states;
    source = audioContext.createBufferSource(); source.buffer = audio; source.connect(audioContext.destination);
    audioStart = audioContext.currentTime + .04;
    source.start(audioStart);
    window.demoState.active = true;
    window.demoState.audioDuration = audio.duration;
    source.onended = () => {if (token === generation) {stop(); setPhase('ready', 'Фраза завершена. Напишите свою или смените голос.');}};
    $('latency').textContent = data.cached ? 'Из кэша' : `${data.prepare_s.toFixed(2)} с`;
    $('duration').textContent = `${audio.duration.toFixed(1)} с`;
    $('metrics-note').textContent = data.cached
      ? 'Эта фраза уже считалась локально. Измените текст, чтобы проверить новую генерацию.'
      : `Голос с загрузкой модели: ${data.tts_s.toFixed(2)} с. Анализ звука: ${(data.timing.seconds * 1000).toFixed(0)} мс. Подготовлена вся фраза, не поток.`;
    setPhase('speaking', 'Говорит. Нажмите «Остановить», чтобы проверить прерывание.');
  } catch (error) {
    if (token !== generation || error.name === 'AbortError') return;
    stop(); setPhase('error', error.message, true);
  }
}
function tick() {
  if (ready) {
    const now = performance.now(), frame = Math.floor((now - epoch) / (1000 / 30));
    position = reducedMotion.matches ? 0 : motion.update(now, !!source);
    if (frame !== lastFrame) {
      lastFrame = frame;
      const speechFrame = source ? Math.floor((audioContext.currentTime - audioStart) * 25) : -1;
      draw(speechFrame >= 0 && speechFrame < states.length ? states[speechFrame] : 0);
    }
  }
  requestAnimationFrame(tick);
}
function updateCount() { $('count').textContent = `${$('text').value.length} / 500`; }
function updateVoice() {
  $('license').textContent = voices.find(v => v.id === $('voice').value)?.license || '';
  $('speak').disabled = !ready || !voices.find(v => v.id === $('voice').value)?.available;
}
$('speak').onclick = speak;
$('stop').onclick = () => stop();
$('voice').onchange = () => {stop('Голос выбран. Нажмите «Произнести».'); updateVoice();};
$('text').oninput = updateCount;
$('text').onkeydown = event => {if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {event.preventDefault(); if (!$('speak').disabled) speak();}};
document.querySelectorAll('[data-example]').forEach(button => {button.onclick = () => {stop('Пример выбран. Его можно отредактировать перед запуском.'); $('text').value = examples[button.dataset.example]; updateCount();};});
window.addEventListener('pagehide', () => stop());
document.addEventListener('visibilitychange', () => {if (document.hidden) stop('Остановлено при скрытии вкладки. Нажмите «Произнести», чтобы начать снова.');});

async function loadImage(url) {const image = new Image(); image.src = url; await image.decode(); return image;}
async function init() {
  updateCount();
  try {
    const responses = await Promise.all([fetch('/status'), fetch('/manifest.json')]);
    if (responses.some(r => !r.ok)) throw Error('Локальные файлы недоступны');
    const [status, meta] = await Promise.all(responses.map(r => r.json()));
    voices = status.voices; manifest = meta;
    for (const voice of voices) $('voice').querySelector(`option[value="${voice.id}"]`).disabled = !voice.available;
    const firstAvailable = voices.find(v => v.available);
    if (!firstAvailable) throw Error('Нет локальных TTS-моделей. См. demos/offline/README.md');
    $('voice').value = firstAvailable.id; updateVoice();
    [$('avatar').width, $('avatar').height] = manifest.size;
    $('library-info').textContent = `Положений головы: ${manifest.poses}. Форм рта для каждого: ${manifest.states}. Всего ${manifest.poses * manifest.states} вариантов подготовлены заранее. Во время демо изображения не генерируются.`;
    let next = 0, loaded = 0;
    await Promise.all(Array.from({length:4}, async () => {
      while (next < manifest.poses) {
        const p = next++, id = String(p).padStart(3, '0');
        const [base, sheet] = await Promise.all([loadImage(`/assets/base/${id}.jpg`), loadImage(`/assets/atlas/${id}.png`)]);
        assets[p] = {base, sheet}; loaded++;
        $('status').textContent = `Загружаю библиотеку лица: ${loaded} / ${manifest.poses}`;
        if (p === 0) $('avatar').getContext('2d').drawImage(base, 0, 0);
      }
    }));
    renderer = new MotionRenderer($('avatar'), manifest, assets);
    motion = new MotionClock(manifest.poses); ready = true; epoch = performance.now();
    setPhase('ready', 'Готово. Можно отключить интернет и проверить любую новую фразу.'); tick();
  } catch (error) {setPhase('error', 'Не удалось подготовить демо: ' + error.message, true);}
}
init();
