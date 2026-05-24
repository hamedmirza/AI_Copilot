import { api } from '@/api/client'
import {
  changePath,
  contentFromArtifactRow,
  proposedFromChange,
} from '@/lib/artifactFileContent'

export interface PatchDiffFile {
  path: string
  original: string
  modified: string
}

export async function loadCoderPatchDiffs(
  projectId: string,
  artifacts: Array<{ artifact_type: string; content: Record<string, unknown> }>,
): Promise<PatchDiffFile[]> {
  const coder = artifacts.find((a) => a.artifact_type === 'coder')
  if (!coder) return []

  const changes = Array.isArray(coder.content.file_changes) ? coder.content.file_changes : []
  const results: PatchDiffFile[] = []

  for (const raw of changes) {
    const row = raw as Record<string, unknown>
    const path = changePath(row)
    if (!path) continue

    let original: string
    try {
      const file = await api.files.read(projectId, path)
      original = file.content
    } catch {
      original = ''
    }

    const modified = contentFromArtifactRow(row, original) ?? proposedFromChange(original, row)
    results.push({ path, original, modified })
  }

  return results
}

export function monacoLanguageForPath(path: string): string {
  const ext = path.split('.').pop()?.toLowerCase() || ''
  const map: Record<string, string> = {
    py: 'python',
    ts: 'typescript',
    tsx: 'typescript',
    js: 'javascript',
    jsx: 'javascript',
    json: 'json',
    md: 'markdown',
    yaml: 'yaml',
    yml: 'yaml',
    css: 'css',
    html: 'html',
  }
  return map[ext] || 'plaintext'
}
