import { applyLineChanges } from '@/lib/applyLineChanges'
import type { RunArtifact } from '@/types/runs'

interface LineChangeRow {
  start_line: number
  end_line: number
  new_content: string
}

export function changePath(row: Record<string, unknown>): string {
  return String(row.path || row.file_path || '').trim()
}

export function proposedFromChange(original: string, row: Record<string, unknown>): string {
  if (typeof row.full_content === 'string') return row.full_content
  const lineChanges = Array.isArray(row.line_changes) ? row.line_changes : []
  if (lineChanges.length) {
    return applyLineChanges(original, lineChanges as LineChangeRow[])
  }
  return original
}

export function artifactRowForPath(
  artifacts: RunArtifact[] | undefined,
  path: string,
): Record<string, unknown> | null {
  if (!artifacts?.length) return null
  for (const artifact of artifacts) {
    const changes = Array.isArray(artifact.content.file_changes) ? artifact.content.file_changes : []
    for (const raw of changes) {
      const row = raw as Record<string, unknown>
      if (changePath(row) === path) return row
    }
  }
  return null
}

export function contentFromArtifactRow(row: Record<string, unknown>, base = ''): string | null {
  if (typeof row.full_content === 'string') return row.full_content
  const lineChanges = Array.isArray(row.line_changes) ? row.line_changes : []
  if (lineChanges.length) return proposedFromChange(base, row)
  return null
}

export function contentFromArtifacts(
  path: string,
  artifacts?: RunArtifact[],
  changeEntry?: Record<string, unknown>,
): string | null {
  const row = changeEntry ?? artifactRowForPath(artifacts, path)
  if (!row) return null
  return contentFromArtifactRow(row)
}
