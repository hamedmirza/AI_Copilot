import { api } from '@/api/client'
import { artifactRowForPath } from '@/lib/artifactFileContent'
import { getLanguage } from '@/lib/utils'
import type { RunArtifact } from '@/types/runs'
import type { EditorTab } from '@/store'

function openResolvedFile(
  path: string,
  content: string,
  openTab: (tab: EditorTab) => void,
): void {
  openTab({ path, content, dirty: false, language: getLanguage(path) })
}

export async function openRunFile(options: {
  projectId: string | null
  runId?: string | null
  path: string
  artifacts?: RunArtifact[]
  inlineContent?: string | null
  changeEntry?: Record<string, unknown>
  openTab: (tab: EditorTab) => void
}): Promise<boolean> {
  const { projectId, runId, path, artifacts, inlineContent, changeEntry, openTab } = options
  if (!path) return false

  if (typeof inlineContent === 'string') {
    openResolvedFile(path, inlineContent, openTab)
    return true
  }

  const row = changeEntry ?? artifactRowForPath(artifacts, path)
  if (row && typeof row.full_content === 'string') {
    openResolvedFile(path, row.full_content, openTab)
    return true
  }

  if (runId) {
    try {
      const data = await api.runs.readWorkspaceFile(runId, path)
      openResolvedFile(path, data.content, openTab)
      return true
    } catch {
      /* fall through */
    }
  }

  if (projectId) {
    try {
      const data = await api.files.read(projectId, path)
      openResolvedFile(path, data.content, openTab)
      return true
    } catch {
      /* fall through */
    }
  }

  return false
}
