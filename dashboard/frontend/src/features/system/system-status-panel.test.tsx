import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import { type SetupStatusResponse } from './api'
import { SystemStatusPanel } from './system-status-panel'

const SECRET_MARKER = 'MARKER-SECRET-MUST-NOT-RENDER'

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api')
  return { ...actual, useSetupStatus: () => mockedResult }
})

let mockedResult: {
  data?: SetupStatusResponse
  isLoading: boolean
  isError: boolean
} = { isLoading: true, isError: false }

async function renderPanel(result: typeof mockedResult) {
  mockedResult = result
  return await render(
    <QueryClientProvider client={new QueryClient()}>
      <SystemStatusPanel />
    </QueryClientProvider>
  )
}

function response(overrides: Partial<SetupStatusResponse>): SetupStatusResponse {
  return {
    state: 'READY',
    providers: {},
    ...overrides,
  }
}

describe('SystemStatusPanel', () => {
  it('toont JARVIS READY wanneer alles geconfigureerd is', async () => {
    const screen = await renderPanel({
      isLoading: false,
      isError: false,
      data: response({
        state: 'READY',
        providers: {
          openai: {
            provider: 'openai',
            status: 'ok',
            ok: true,
            configured: true,
            summary: 'OpenAI credentials aanwezig.',
          },
        },
      }),
    })

    await expect.element(screen.getByText('JARVIS READY')).toBeInTheDocument()
    await expect
      .element(screen.getByText('OpenAI credentials aanwezig.'))
      .toBeInTheDocument()
  })

  it('toont SETUP REQUIRED met het herstelcommando', async () => {
    const screen = await renderPanel({
      isLoading: false,
      isError: false,
      data: response({ state: 'SETUP_REQUIRED' }),
    })

    await expect.element(screen.getByText('SETUP REQUIRED')).toBeInTheDocument()
    await expect
      .element(screen.getByText('python -m tools.setup_wizard'))
      .toBeInTheDocument()
  })

  it('toont CONFIGURATION ERROR met de reden per provider', async () => {
    const screen = await renderPanel({
      isLoading: false,
      isError: false,
      data: response({
        state: 'CONFIGURATION_ERROR',
        providers: {
          coinbase: {
            provider: 'coinbase',
            status: 'invalid',
            ok: false,
            configured: false,
            summary: 'Coinbase private key kon niet worden gelezen.',
            detail: 'COINBASE_API_SECRET heeft een onbekend formaat.',
          },
        },
      }),
    })

    await expect
      .element(screen.getByText('CONFIGURATION ERROR'))
      .toBeInTheDocument()
    await expect
      .element(screen.getByText('COINBASE_API_SECRET heeft een onbekend formaat.'))
      .toBeInTheDocument()
  })

  it('valt terug op STATUS ONBEKEND als de backend faalt', async () => {
    const screen = await renderPanel({ isLoading: false, isError: true })

    await expect.element(screen.getByText('STATUS ONBEKEND')).toBeInTheDocument()
  })

  it('rendert nooit een waarde die op een secret lijkt', async () => {
    const screen = await renderPanel({
      isLoading: false,
      isError: false,
      data: response({
        state: 'READY',
        providers: {
          coinbase: {
            provider: 'coinbase',
            status: 'ok',
            ok: true,
            configured: true,
            summary: 'Coinbase credentials aanwezig (Ed25519).',
            // De backend stuurt dit nooit mee; mocht dat ooit veranderen,
            // dan mag deze component het alsnog niet tonen.
            facts: { api_secret: SECRET_MARKER },
          },
        },
      }),
    })

    await expect
      .element(screen.getByText('Coinbase credentials aanwezig (Ed25519).'))
      .toBeInTheDocument()
    expect(document.body.textContent).not.toContain(SECRET_MARKER)
  })
})
