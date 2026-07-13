import { File, FileCode2, FileJson, FileSpreadsheet, FileText, Image, Presentation } from 'lucide-react'

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
