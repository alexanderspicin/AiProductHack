import { createRequire } from 'node:module'
import { dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from '../../../frontend/node_modules/vitest/dist/config.js'
const require = createRequire(new URL('../../../frontend/package.json', import.meta.url))
export default defineConfig({
  root: fileURLToPath(new URL('../../../', import.meta.url)),
  esbuild: { jsx: 'automatic' },
  resolve: { alias: {
    vitest: fileURLToPath(new URL('../../../frontend/node_modules/vitest/dist/index.js', import.meta.url)),
    react: dirname(require.resolve('react/package.json')),
    '@pipecat-ai/client-js': require.resolve('@pipecat-ai/client-js'),
    '@pipecat-ai/websocket-transport': require.resolve('@pipecat-ai/websocket-transport'),
  } },
  test: { environment: 'happy-dom', include: ['artifacts/runs/18_presentation_audit/caption-repro.test.tsx'] },
})
