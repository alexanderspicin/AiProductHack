import * as THREE from "three";

export interface SceneHandle {
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  renderer: THREE.WebGLRenderer;
  onTick: (cb: (deltaSeconds: number) => void) => void;
}

export function createScene(canvas: HTMLCanvasElement): SceneHandle {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x111111);

  const camera = new THREE.PerspectiveCamera(
    30,
    window.innerWidth / window.innerHeight,
    0.1,
    20
  );
  // Pulled back from a too-tight headshot framing to a chest-up shot, aimed at
  // roughly head height (avatar rig's head sits around y=1.5-1.6).
  camera.position.set(0, 1.4, 2.4);
  camera.lookAt(0, 1.5, 0);

  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.setPixelRatio(window.devicePixelRatio);

  const keyLight = new THREE.DirectionalLight(0xffffff, 1.2);
  keyLight.position.set(1, 1.5, 1);
  scene.add(keyLight);
  scene.add(new THREE.AmbientLight(0xffffff, 0.6));

  window.addEventListener("resize", () => {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
  });

  const tickCallbacks: Array<(deltaSeconds: number) => void> = [];
  const clock = new THREE.Clock();

  function animate() {
    requestAnimationFrame(animate);
    const delta = clock.getDelta();
    for (const cb of tickCallbacks) cb(delta);
    renderer.render(scene, camera);
  }
  animate();

  return {
    scene,
    camera,
    renderer,
    onTick: (cb) => tickCallbacks.push(cb),
  };
}
