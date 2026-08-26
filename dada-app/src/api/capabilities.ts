import { apiRequest } from './client'

export type Capabilities = {
  supported_image_media_types: string[]
  max_file_bytes: number
  max_project_files: number
  upload_chunk_bytes: number
  supported_task_types: Array<'classification' | 'detection' | 'segmentation'>
  supported_annotation_modes: Array<'single' | 'consensus'>
  consensus_resolvers: Record<string, string[]>
  realtime_transport: 'websocket' | 'polling'
}

export function getCapabilities(): Promise<Capabilities> {
  return apiRequest<Capabilities>('/api/v1/capabilities')
}
