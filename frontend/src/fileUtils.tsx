import { File, FileCode2, FileJson, FileSpreadsheet, FileText, Image, Presentation } from 'lucide-react'

export function formatSize(size: number) {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

export function FileTypeIcon({ name }: { name: string }) {
  const extension = name.split('.').pop()?.toLowerCase() ?? ''
  const Icon = (() => {
    if (['png', 'jpg', 'jpeg', 'webp', 'gif'].includes(extension)) return Image
    if (['csv', 'tsv', 'xls', 'xlsx'].includes(extension)) return FileSpreadsheet
    if (['ppt', 'pptx'].includes(extension)) return Presentation
    if (['json', 'jsonl'].includes(extension)) return FileJson
    if (['py', 'js', 'jsx', 'ts', 'tsx', 'html', 'css', 'yaml', 'yml'].includes(extension)) return FileCode2
    if (['txt', 'md', 'log', 'doc', 'docx'].includes(extension)) return FileText
    return File
  })()
  return <Icon className="file-icon" size={19} strokeWidth={1.7} aria-hidden="true" />
}

export function arrayBufferToBase64(buffer: ArrayBuffer) {
  const bytes = new Uint8Array(buffer)
  const chunkSize = 0x8000
  let binary = ''
  for (let index = 0; index < bytes.length; index += chunkSize) {
    const chunk = bytes.subarray(index, index + chunkSize)
    binary += String.fromCharCode(...chunk)
  }
  return window.btoa(binary)
}
