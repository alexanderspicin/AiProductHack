import { mkdir, copyFile } from 'node:fs/promises'
const source = new URL('../../../frontend/public/models/avatar.glb', import.meta.url)
const directory = new URL('../public/models/', import.meta.url)
await mkdir(directory, { recursive: true })
await copyFile(source, new URL('avatar.glb', directory))
console.log('Original team avatar prepared from ../frontend/public/models/avatar.glb')
