import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { PresentationScreen } from '../src/text/PresentationScreen'
import type { Bootstrap } from '../src/text/types'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })
test('methodist switches character without exposing model or keys', async () => {
  const data: Bootstrap = { scenarios: [], sessions: [], runtime: {external_processing:true,is_demo:false,mode:'practice'},
    presentation: {revision:1,voice_mode:'avatar',avatar_profile:'tavus_sergei',allow_audio_fallback:true},
    avatar_profiles: [
      {id:'tavus_sergei',title:'Даниил',description:'Cartesia Sergei + Tavus Daniel',provider:'tavus'},
      {id:'anam_tatiana',title:'Татьяна',description:'Cartesia Tatiana + Anam Cara',provider:'anam'},
    ] }
  const fetcher = vi.fn(async (_url, options) => new Response(options.body, {status:200}))
  vi.stubGlobal('fetch', fetcher)
  render(<PresentationScreen data={data} reload={vi.fn()} notify={vi.fn()} />)
  fireEvent.click(screen.getByRole('radio', {name:/Татьяна/}))
  fireEvent.click(screen.getByRole('button', {name:'Сохранить персонажа'}))
  await waitFor(() => expect(fetcher).toHaveBeenCalledOnce())
  expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({...data.presentation,avatar_profile:'anam_tatiana'})
  expect(screen.queryByRole('combobox')).toBeNull()
})
