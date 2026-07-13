import { arrayBufferToBase64 } from './fileDataUtils'
import type { Attachment, UploadedFilePayload } from './types'

export async function buildUploadPayloads(files: Attachment[]): Promise<UploadedFilePayload[]> {
  if (files.length === 0) return []
  return Promise.all(
    files.map(async (item) => ({
      name: item.name,
      size: item.size,
      mime_type: item.file.type || undefined,
      content_base64: arrayBufferToBase64(await item.file.arrayBuffer()),
    })),
  )
}
