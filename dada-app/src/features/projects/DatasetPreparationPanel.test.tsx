import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AuthContext, type AuthContextValue } from '../auth/auth-context'
import { DatasetPreparationPanel } from './DatasetPreparationPanel'
import type { AnnotationImport, DatasetLayoutSummary, Project } from './types'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const project: Project = {
  id: 'project-1', name: 'Road defects', description: null, task_type: 'detection',
  status: 'draft', owner_id: 'user-1', acquisition_strategy: 'random',
  dataset_layout: 'split', initial_training_size: null, test_set_size: 4,
  test_set_percentage: null, validation_set_size: 2, validation_set_percentage: null,
  iteration_batch_size: 3, dataset_prepared_at: '2026-09-24T12:00:00Z', version: 1,
  created_at: '2026-09-24T12:00:00Z', updated_at: '2026-09-24T12:00:00Z',
}

const layout: DatasetLayoutSummary = {
  dataset_layout: 'split', prepared_at: '2026-09-24T12:00:00Z', train_size: 6,
  validation_size: 2, test_size: 4, first_training_batch_size: 3,
  training_pool_size: 3, batch_ids: ['a', 'b', 'c'], annotation_import_id: 'import-1',
}

function renderPanel(
  labelImport: Partial<AnnotationImport>,
  summary: DatasetLayoutSummary = layout,
) {
  const fetch = vi.fn().mockImplementation((url: string) => {
    const payload = url.endsWith('/dataset-layout') ? summary : {
      id: 'import-1', project_id: 'project-1', format: 'yolo_detection',
      parser_version: 'yolo-detection/1', created_by: 'user-1', files: [],
      created_at: '2026-09-24T12:00:00Z', validated_at: null, accepted_at: null,
      report: null, ...labelImport,
    }
    return Promise.resolve(new Response(JSON.stringify(payload), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    }))
  })
  vi.stubGlobal('fetch', fetch)
  const context: AuthContextValue = {
    user: {
      id: 'user-1', username: 'owner', display_name: 'Owner',
      is_administrator: false, is_active: true, version: 1,
      created_at: '2026-09-24T12:00:00Z',
    },
    token: 'token', isLoading: false, login: vi.fn(), logout: vi.fn(),
  }
  render(<QueryClientProvider client={new QueryClient()}>
    <AuthContext.Provider value={context}>
      <DatasetPreparationPanel project={project} onActivated={vi.fn()} />
    </AuthContext.Provider>
  </QueryClientProvider>)
  return fetch
}

function labelFile(path: string, content: string) {
  const file = new File([content], path.split('/').pop()!)
  const bytes = new TextEncoder().encode(content)
  Object.defineProperty(file, 'webkitRelativePath', { value: path })
  // jsdom's File lacks the arrayBuffer() every supported browser provides.
  Object.defineProperty(file, 'arrayBuffer', { value: async () => bytes.buffer })
  return file
}

describe('DatasetPreparationPanel', () => {
  it('shows the initial work and the remaining unlabeled pool', async () => {
    renderPanel({ status: 'accepted' })

    expect(await screen.findByText('Unlabeled training pool')).toBeInTheDocument()
    expect(screen.getByText('First training batch').nextSibling).toHaveTextContent('3 images')
    expect(screen.getByText('Unlabeled training pool').nextSibling).toHaveTextContent('3 images')
  })

  it('blocks activation until a pending import is accepted or discarded', async () => {
    renderPanel({
      status: 'rejected',
      files: [{ client_file_id: 'f1', relative_path: 'camera-a/1.txt', size_bytes: 1, sha256: 'x', received: true }],
      report: {
        labelled_images: 0, objects: 0, unlabelled_images: 12,
        errors: [{ code: 'unknown_class_index', client_file_id: 'f1', detail: 'line 1: 7' }],
      },
    })

    expect(await screen.findByText(/camera-a\/1\.txt: line 1: 7/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Activate project/ })).toBeDisabled()
    expect(screen.queryByRole('button', { name: /Accept labels/ })).not.toBeInTheDocument()
  })

  it('reads the chosen label files before clearing the picker', async () => {
    const fetch = renderPanel({ status: 'uploading' }, { ...layout, annotation_import_id: null })
    const input = await screen.findByLabelText('Label files')
    const selection = [labelFile('labels/camera-a/0001.txt', '0 0.5 0.5 0.1 0.1\n')]
    // Browsers empty the very FileList they returned when the input's value is reset.
    Object.defineProperty(input, 'files', { configurable: true, value: selection })
    Object.defineProperty(input, 'value', {
      configurable: true, get: () => '', set: () => { selection.length = 0 },
    })

    fireEvent.change(input)

    await waitFor(() => expect(fetch).toHaveBeenCalledWith(
      expect.stringMatching(/\/projects\/project-1\/annotation-imports$/),
      expect.anything(),
    ))
    const create = fetch.mock.calls.find(([url]) => /\/annotation-imports$/.test(url))!
    expect(JSON.parse(create[1].body).files).toMatchObject([
      { relative_path: 'camera-a/0001.txt' },
    ])
    expect(screen.queryByText(/No \.txt label files/)).not.toBeInTheDocument()
  })

  it('allows activation once the import is accepted', async () => {
    renderPanel({ status: 'accepted' })

    expect(await screen.findByText('Labels accepted')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Activate project/ })).toBeEnabled()
  })
})
