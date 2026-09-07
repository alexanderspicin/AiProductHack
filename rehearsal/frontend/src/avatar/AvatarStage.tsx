import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { ArmGestures } from './armGestures'
import { loadAvatar } from './avatarLoader'
import { BlendshapeCompositor } from './blendshapeCompositor'
import { BodyAnimator } from './bodyAnimator'
import { IdleFace } from './idleFace'
import { AvatarPresence } from './presence'
import type { AvatarStream } from '../voice/AvatarStream'
import { VisemeDriver } from './visemeDriver'

export function AvatarStage({ stream, name }: { stream: AvatarStream; name: string }) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const [status, setStatus] = useState<'loading' | 'ready' | 'missing' | 'unsupported'>('loading')
  useEffect(() => {
    const element = canvas.current
    if (!element) return
    let renderer: THREE.WebGLRenderer
    try { renderer = new THREE.WebGLRenderer({ canvas: element, antialias: true, alpha: false }) }
    catch { setStatus('unsupported'); return }
    renderer.outputColorSpace = THREE.SRGBColorSpace
    const scene = new THREE.Scene(); scene.background = new THREE.Color(0xe7efeb)
    const camera = new THREE.PerspectiveCamera(29, 1, .1, 20)
    camera.position.set(0, 1.42, 2.35); camera.lookAt(0, 1.48, 0)
    scene.add(new THREE.HemisphereLight(0xffffff, 0x7c9087, 1.45))
    const key = new THREE.DirectionalLight(0xffffff, 2.1); key.position.set(1.5, 2.4, 2.2); scene.add(key)
    const rim = new THREE.DirectionalLight(0xbadbcf, 1.0); rim.position.set(-2, 1.8, -1); scene.add(rim)
    const presence = new AvatarPresence()
    const compositor = new BlendshapeCompositor()
    const driver = new VisemeDriver(presence, compositor)
    const unsubscribe = stream.subscribe(event => driver.handleAvatarEvent(event))
    const face = new IdleFace(presence, compositor)
    const body = new BodyAnimator(presence)
    const arms = new ArmGestures(presence)
    let alive = true, frame = 0, previous = performance.now()
    const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches
    loadAvatar(scene).then(avatar => {
      if (!alive) return
      if (!avatar) { setStatus('missing'); return }
      compositor.setAvatar(avatar); body.setAvatar(avatar); arms.setAvatar(avatar); setStatus('ready')
    })
    const resize = new ResizeObserver(entries => {
      const box = entries[0]?.contentRect
      if (!box || !box.width || !box.height) return
      renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2)); renderer.setSize(box.width, box.height, false)
      camera.aspect = box.width / box.height; camera.updateProjectionMatrix()
    }); resize.observe(element)
    const tick = (now: number) => {
      if (!alive) return
      const delta = Math.min((now - previous) / 1000, .1); previous = now
      presence.botSpeaking = stream.botSpeaking; presence.userSpeaking = stream.userSpeaking
      driver.update(delta)
      if (!reduced) { face.update(delta); body.update(delta); arms.update(delta) }
      else compositor.set('idle', {})
      compositor.apply(); renderer.render(scene, camera); frame = requestAnimationFrame(tick)
    }; frame = requestAnimationFrame(tick)
    return () => {
      alive = false; cancelAnimationFrame(frame); resize.disconnect(); unsubscribe()
      scene.traverse(object => {
        const mesh = object as THREE.Mesh
        mesh.geometry?.dispose?.()
        const materials = Array.isArray(mesh.material) ? mesh.material : mesh.material ? [mesh.material] : []
        materials.forEach(material => { Object.values(material).forEach(value => { if (value instanceof THREE.Texture) value.dispose() }); material.dispose() })
      })
      renderer.dispose()
    }
  }, [stream])
  return <div className="avatar-stage" aria-label={`3D-персонаж ${name}`}>
    <canvas ref={canvas} aria-hidden="true" />
    {status !== 'ready' && <div className="avatar-status" role="status">
      {status === 'loading' && 'Загружаем персонажа…'}
      {status === 'missing' && <>Модель персонажа не найдена.<small>Добавьте файл public/models/avatar.glb.</small></>}
      {status === 'unsupported' && <>3D недоступно в этом браузере.<small>Текстовый разговор продолжает работать.</small></>}
    </div>}
  </div>
}
