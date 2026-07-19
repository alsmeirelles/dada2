export type TaskType = 'classification' | 'detection' | 'segmentation'
export type ProjectStatus =
  | 'draft'
  | 'ingesting'
  | 'ready'
  | 'active'
  | 'training'
  | 'completed'
  | 'failed'

export type Project = {
  id: string
  name: string
  description: string | null
  task_type: TaskType
  status: ProjectStatus
  owner_id: string
  initial_training_size: number
  test_set_size: number
  iteration_batch_size: number
  version: number
  created_at: string
  updated_at: string
  media_count?: number
  completed_annotations?: number
}

export type ProjectClassInput = {
  id: string
  name: string
  color: string
}

export type ProjectDraft = {
  name: string
  description: string
  taskType: TaskType
  classes: ProjectClassInput[]
  initialTrainingSize: number
  testSetSize: number
  iterationBatchSize: number
  collaborators: string[]
}

export type Page<T> = { items: T[]; next_cursor: string | null }
