import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AuthContext, type AuthContextValue } from '../auth/auth-context'
import { NewProjectPage } from './NewProjectPage'
import { learningCatalog } from './learning-catalog.fixture'
import { consensusPipelines } from './resolver-catalog.fixture'

function image(path: string) {
  const bytes = new TextEncoder().encode(path)
  const file = new File([bytes], path.split('/').at(-1)!, { type: 'image/jpeg' })
  Object.defineProperty(file, 'webkitRelativePath', { value: path })
  Object.defineProperty(file, 'arrayBuffer', { value: () => Promise.resolve(bytes.buffer) })
  return file
}

function names(count: number, start = 1) {
  return Array.from({ length: count }, (_, index) => `${String(start + index).padStart(4, '0')}.jpg`)
}

async function chooseFolder(root: string, files: string[]) {
  const input = screen.getByLabelText('Image folder')
  Object.defineProperty(input, 'files', { value: files.map((name) => image(`${root}/${name}`)), configurable: true })
  fireEvent.change(input)
  await waitFor(() => expect(screen.queryByText(/Checking images/)).not.toBeInTheDocument(), { timeout: 10_000 })
}

function readyCount() {
  return Number(within(screen.getByText('Images ready').parentElement!).getByRole('strong').textContent)
}

function renderWizard(stepsAfterClasses = 3) {
  vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => Promise.resolve(new Response(JSON.stringify(
    url.includes('/users/eligible-annotators')
      ? { items: [
          { id: 'owner', username: 'owner', display_name: 'Owner' },
          { id: 'ana-id', username: 'ana', display_name: 'Ana' },
          { id: 'bruno-id', username: 'bruno', display_name: 'Bruno' },
        ], next_cursor: null }
      : { consensus_pipelines: consensusPipelines, supported_image_media_types: ['image/jpeg', 'image/png', 'image/webp', 'image/heic', 'image/heif'], ...learningCatalog },
  ), { status: 200, headers: { 'Content-Type': 'application/json' } }))))
  const context: AuthContextValue = {
    user: { id: 'owner', username: 'owner', display_name: 'Owner', is_administrator: false, is_active: true, version: 1, created_at: '2026-09-30T12:00:00Z' },
    token: 'token', isLoading: false, sessionExpired: false, login: vi.fn(), logout: vi.fn(),
  }
  render(<QueryClientProvider client={new QueryClient()}>
    <AuthContext.Provider value={context}><MemoryRouter><NewProjectPage /></MemoryRouter></AuthContext.Provider>
  </QueryClientProvider>)
  fireEvent.change(screen.getByPlaceholderText('Road surface defects'), { target: { value: 'Road defects' } })
  fireEvent.click(screen.getByRole('button', { name: /Continue/ }))
  fireEvent.change(screen.getByPlaceholderText('Pothole'), { target: { value: 'Pothole' } })
  for (let step = 0; step < stepsAfterClasses; step += 1) fireEvent.click(screen.getByRole('button', { name: /Continue/ }))
}

beforeEach(() => sessionStorage.clear())
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const HASHING_TIMEOUT = { timeout: 20_000 }

describe('I6-01: selecting images from several folders', () => {
  beforeEach(() => {
    renderWizard()
    expect(screen.getByRole('heading', { name: 'Select images' })).toBeInTheDocument()
  })

  it('adds every image of a second folder even when it reuses the first folder\'s file names', HASHING_TIMEOUT, async () => {
    await chooseFolder('north', names(25))
    await chooseFolder('south', names(25))

    expect(readyCount()).toBe(50)
  })

  it('states the dataset size that the default 10% validation set actually needs', HASHING_TIMEOUT, async () => {
    await chooseFolder('north', names(25))

    expect(screen.getByText(/need at least 34 images/)).toBeInTheDocument()
    await chooseFolder('south', names(9, 26))
    expect(readyCount()).toBe(34)
    expect(screen.getByRole('button', { name: /Continue/ })).toBeEnabled()
  })
})

describe('consensus resolution settings in the wizard', () => {
  it('selects project annotators from active users returned by the API', async () => {
    renderWizard(2)

    expect(screen.queryByLabelText(/Annotator usernames/)).not.toBeInTheDocument()
    const ana = await screen.findByRole('checkbox', { name: /Ana.*@ana/ })
    const bruno = screen.getByRole('checkbox', { name: /Bruno.*@bruno/ })
    fireEvent.click(ana)
    fireEvent.click(bruno)

    expect(ana).toBeChecked()
    expect(bruno).toBeChecked()
    expect(screen.queryByRole('checkbox', { name: /Owner.*@owner/ })).not.toBeInTheDocument()
  })

  it('configures the task pipeline from the catalog and summarizes it before creation', HASHING_TIMEOUT, async () => {
    renderWizard(2)
    fireEvent.click(await screen.findByRole('checkbox', { name: /Ana.*@ana/ }))
    fireEvent.click(screen.getByRole('checkbox', { name: /Bruno.*@bruno/ }))
    fireEvent.click(screen.getByLabelText('Consensus annotation'))

    expect(await screen.findByText('Two stage detection consensus')).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /Dawid skene/ })).toBeDisabled()
    const votes = screen.getByRole('spinbutton', { name: 'Minimum support, votes' })
    const outOf = screen.getByRole('spinbutton', { name: 'Minimum support, out of' })
    fireEvent.change(votes, { target: { value: '1' } })
    fireEvent.change(outOf, { target: { value: '2' } })
    expect(screen.getByText('Fix the resolver settings marked above.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Continue/ })).toBeDisabled()

    fireEvent.change(votes, { target: { value: '3' } })
    fireEvent.change(outOf, { target: { value: '4' } })
    fireEvent.click(screen.getByLabelText(/Require an independent adjudicator/))
    fireEvent.click(screen.getByRole('button', { name: /Continue/ }))
    await chooseFolder('north', names(40))
    fireEvent.click(screen.getByRole('button', { name: /Continue/ }))

    expect(screen.getByText('Minimum support: 3/4 · Minimum median IoU: 0.5')).toBeInTheDocument()
    expect(screen.getByText('Must be independent')).toBeInTheDocument()
  })
})

describe('acquisition loop settings in the wizard', () => {
  it('asks for the iteration limit and the solution settings, and shows them before creation', HASHING_TIMEOUT, async () => {
    renderWizard(1)
    expect(screen.getByRole('heading', { name: 'Acquisition, layout, and sizes' })).toBeInTheDocument()

    fireEvent.change(screen.getByRole('spinbutton', { name: /Maximum acquisition iterations/ }), { target: { value: '6' } })
    fireEvent.click(screen.getByLabelText('Active learning'))
    expect(await screen.findByRole('radio', { name: /Deterministic/ })).toBeChecked()
    expect(screen.getByRole('radio', { name: /DADA/ })).toBeDisabled()
    expect(screen.getByText(/a required library is not installed/)).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText(/Metric target/), { target: { value: '1.5' } })
    expect(screen.getByText('The metric target must be greater than 0 and at most 1.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Continue/ })).toBeDisabled()

    fireEvent.change(screen.getByLabelText(/Metric target/), { target: { value: '0.8' } })
    fireEvent.change(screen.getByLabelText(/Evaluate every/), { target: { value: '2' } })
    fireEvent.click(screen.getByRole('button', { name: /Continue/ }))
    fireEvent.click(screen.getByRole('button', { name: /Continue/ }))
    await chooseFolder('north', names(40))
    fireEvent.click(screen.getByRole('button', { name: /Continue/ }))

    expect(screen.getByText('Deterministic (development) · mAP@50 every 2 iterations · stops at 0.8')).toBeInTheDocument()
    expect(screen.getByText('6 acquisition iterations')).toBeInTheDocument()
  })

  it('offers HEIC and HEIF when the API accepts them', () => {
    renderWizard()

    expect(screen.getByLabelText('Image folder')).toHaveAttribute('accept', expect.stringContaining('image/heic'))
    expect(screen.getByText(/HEIC, and HEIF · nested folders included/)).toBeInTheDocument()
  })
})
