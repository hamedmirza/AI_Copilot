import { useCallback, useEffect, useState } from 'react'
import { api } from '@/api/client'
import { useProjectStore } from '@/store'
import SummaryChart from './SummaryChart'
import SkillChart from './SkillChart'

interface ProjectMetrics {
  successRate: number
  failureRate: number
  skillImprovements: { date: string; score: number }[]
}

export function ReportingWorkbenchPanel() {
  const projectId = useProjectStore((s) => s.currentProjectId)
  const projects = useProjectStore((s) => s.projects)
  const [metrics, setMetrics] = useState<ProjectMetrics | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadMetrics = useCallback(async (id: string) => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.reporting.metrics(id)
      setMetrics({
        successRate: Number(data.successRate ?? 0),
        failureRate: Number(data.failureRate ?? 0),
        skillImprovements: Array.isArray(data.skillImprovements)
          ? (data.skillImprovements as ProjectMetrics['skillImprovements'])
          : [],
      })
    } catch (e) {
      console.error(e)
      setError('Failed to load metrics')
      setMetrics(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!projectId) {
      setMetrics(null)
      return
    }
    void loadMetrics(projectId)
  }, [projectId, loadMetrics])

  if (!projectId) {
    return (
      <p className="p-4 text-sm text-[var(--text-secondary)]">
        Select a project in Manage Projects to view reporting.
      </p>
    )
  }

  const projectName = String(projects.find((p) => p.id === projectId)?.name ?? projectId)

  if (loading) {
    return <p className="p-4 text-sm text-[var(--text-secondary)]">Loading metrics…</p>
  }

  if (error || !metrics) {
    return (
      <p className="p-4 text-sm text-[var(--error)]">
        {error ?? 'No metrics available'}
      </p>
    )
  }

  return (
    <div className="flex flex-col h-full overflow-auto p-3 gap-4">
      <h2 className="text-sm font-medium shrink-0">{projectName} — Reporting</h2>
      <SummaryChart successRate={metrics.successRate} failureRate={metrics.failureRate} />
      <SkillChart data={metrics.skillImprovements} />
    </div>
  )
}
