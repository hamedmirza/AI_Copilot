import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertTriangle, CheckCircle2, Clock3, ListTodo, LoaderCircle, MessageSquareWarning, RefreshCw } from 'lucide-react'
import { api } from '@/api/client'
import { formatRelativeChatTime } from '@/components/Chat/types'
import { Button } from '@/components/ui/primitives'
import { useProjectStore, useUIStore } from '@/store'

interface KanbanCard {
  run_id: string
  task_id: string
  chat_session_id?: string | null
  title: string
  status: string
  current_stage?: string | null
  task_kind?: string | null
  deliverable_kind?: string | null
  created_at: string
  updated_at: string
  failure_class?: string | null
  failure_subclass?: string | null
  error_message?: string | null
  mismatch_classes?: string[]
  warnings?: string[]
  approval_override?: boolean
  operator_feedback_present?: boolean
  retry_count?: number
  review_attempts?: number
  summary_changed_files?: string[]
}

interface KanbanColumn {
  id: string
  title: string
  count: number
  items: KanbanCard[]
}

interface KanbanPayload {
  project: { id: string; name: string; description?: string | null }
  summary: {
    total_runs: number
    queued_runs: number
    active_runs: number
    clarification_runs: number
    approval_runs: number
    completed_runs: number
    attention_runs: number
    success_rate: number
    failure_rate: number
  }
  columns: KanbanColumn[]
  generated_at: string
}

const STATUS_TONES: Record<string, string> = {
  pending: 'bg-[#4b5563]/20 text-[#d1d5db]',
  running: 'bg-sky-500/15 text-sky-300',
  awaiting_clarification: 'bg-amber-500/15 text-amber-300',
  awaiting_approval: 'bg-indigo-500/15 text-indigo-300',
  completed: 'bg-emerald-500/15 text-emerald-300',
  blocked: 'bg-rose-500/15 text-rose-300',
  failed: 'bg-rose-500/15 text-rose-300',
  changes_requested: 'bg-orange-500/15 text-orange-300',
  cancelled: 'bg-slate-500/15 text-slate-300',
}

const COLUMN_ACCENTS: Record<string, string> = {
  queued: 'border-t-slate-400/60',
  active: 'border-t-sky-400/70',
  clarification: 'border-t-amber-400/70',
  approval: 'border-t-indigo-400/70',
  completed: 'border-t-emerald-400/70',
  attention: 'border-t-rose-400/70',
}

function SummaryCard({
  label,
  value,
  note,
  icon: Icon,
}: {
  label: string
  value: string | number
  note: string
  icon: typeof Clock3
}) {
  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[linear-gradient(180deg,rgba(18,24,38,0.96),rgba(11,16,28,0.96))] p-4 shadow-[0_18px_45px_rgba(0,0,0,0.24)]">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--text-secondary)]">{label}</div>
          <div className="mt-2 text-3xl font-semibold text-white">{value}</div>
        </div>
        <div className="rounded-2xl border border-white/10 bg-white/5 p-3 text-[var(--accent)]">
          <Icon size={20} />
        </div>
      </div>
      <div className="mt-3 text-sm text-[var(--text-secondary)]">{note}</div>
    </div>
  )
}

function RunCard({ card }: { card: KanbanCard }) {
  const requestOpenRunDrawer = useUIStore((s) => s.requestOpenRunDrawer)
  const statusTone = STATUS_TONES[card.status] || 'bg-white/10 text-white'
  const warningText = card.warnings?.[0] || card.error_message || card.failure_subclass || card.failure_class || ''

  return (
    <button
      type="button"
      onClick={() => requestOpenRunDrawer(card.run_id, 'conversation')}
      className="w-full rounded-2xl border border-white/8 bg-[linear-gradient(180deg,rgba(21,27,41,0.98),rgba(12,16,27,0.98))] p-4 text-left shadow-[0_16px_35px_rgba(0,0,0,0.22)] transition hover:-translate-y-0.5 hover:border-[var(--accent)]/40 hover:shadow-[0_20px_40px_rgba(0,0,0,0.28)]"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="line-clamp-2 text-sm font-semibold leading-5 text-white">{card.title}</div>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-[var(--text-secondary)]">
            <span className={`rounded-full px-2 py-1 font-medium ${statusTone}`}>{card.status.replaceAll('_', ' ')}</span>
            {card.current_stage && <span>{card.current_stage}</span>}
            {card.task_kind && <span>{card.task_kind}</span>}
            {card.deliverable_kind && <span>{card.deliverable_kind}</span>}
          </div>
        </div>
        <div className="text-right text-[11px] text-[var(--text-secondary)]">
          <div>{formatRelativeChatTime(card.updated_at)}</div>
          <div className="mt-1 font-mono text-[10px] text-white/60">{card.run_id.slice(0, 8)}</div>
        </div>
      </div>

      {(card.mismatch_classes?.length || card.approval_override || card.retry_count || card.review_attempts) ? (
        <div className="mt-3 flex flex-wrap gap-2 text-[10px]">
          {card.mismatch_classes?.slice(0, 2).map((item) => (
            <span key={item} className="rounded-full bg-amber-500/12 px-2 py-1 text-amber-300">
              {item.replaceAll('_', ' ')}
            </span>
          ))}
          {card.approval_override ? (
            <span className="rounded-full bg-rose-500/12 px-2 py-1 text-rose-300">override</span>
          ) : null}
          {card.retry_count ? (
            <span className="rounded-full bg-slate-500/15 px-2 py-1 text-slate-200">{card.retry_count} retries</span>
          ) : null}
          {card.review_attempts ? (
            <span className="rounded-full bg-slate-500/15 px-2 py-1 text-slate-200">{card.review_attempts} reviews</span>
          ) : null}
        </div>
      ) : null}

      {warningText ? (
        <div className="mt-3 rounded-xl border border-amber-500/15 bg-amber-500/8 px-3 py-2 text-xs leading-5 text-amber-100">
          {warningText}
        </div>
      ) : null}

      {card.summary_changed_files?.length ? (
        <div className="mt-3 flex flex-wrap gap-2 text-[10px] text-[var(--text-secondary)]">
          {card.summary_changed_files.map((path) => (
            <span key={path} className="rounded-full border border-white/8 bg-white/5 px-2 py-1 font-mono">
              {path}
            </span>
          ))}
        </div>
      ) : null}
    </button>
  )
}

function Column({ column }: { column: KanbanColumn }) {
  return (
    <section className={`flex min-w-[320px] max-w-[360px] flex-1 flex-col rounded-[24px] border border-[var(--border)] border-t-4 ${COLUMN_ACCENTS[column.id] || 'border-t-white/20'} bg-[linear-gradient(180deg,rgba(10,14,24,0.94),rgba(15,19,31,0.98))]`}>
      <div className="flex items-center justify-between border-b border-white/8 px-4 py-4">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-[0.16em] text-white/90">{column.title}</h2>
          <p className="mt-1 text-xs text-[var(--text-secondary)]">{column.count} runs</p>
        </div>
        <div className="rounded-full bg-white/6 px-3 py-1 text-xs font-semibold text-white">{column.count}</div>
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4">
        {column.items.length ? (
          column.items.map((card) => <RunCard key={card.run_id} card={card} />)
        ) : (
          <div className="rounded-2xl border border-dashed border-white/10 bg-white/[0.03] px-4 py-6 text-sm text-[var(--text-secondary)]">
            No runs in this lane.
          </div>
        )}
      </div>
    </section>
  )
}

export function KanbanWorkbenchPanel() {
  const projectId = useProjectStore((s) => s.currentProjectId)
  const [data, setData] = useState<KanbanPayload | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!projectId) {
      setData(null)
      return
    }
    setLoading(true)
    setError(null)
    try {
      const payload = await api.projects.kanban(projectId)
      setData(payload as unknown as KanbanPayload)
    } catch (err) {
      console.error(err)
      setError(err instanceof Error ? err.message : 'Failed to load Kanban board')
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (!projectId) return undefined
    const timer = window.setInterval(() => {
      void load()
    }, 15000)
    return () => window.clearInterval(timer)
  }, [load, projectId])

  const summaryCards = useMemo(() => {
    if (!data) return []
    return [
      { label: 'Total Runs', value: data.summary.total_runs, note: `${data.summary.active_runs} active and ${data.summary.queued_runs} queued`, icon: ListTodo },
      { label: 'Needs Review', value: data.summary.approval_runs, note: `${data.summary.clarification_runs} waiting on clarification`, icon: MessageSquareWarning },
      { label: 'Completed', value: data.summary.completed_runs, note: `${data.summary.success_rate}% success across terminal runs`, icon: CheckCircle2 },
      { label: 'Attention', value: data.summary.attention_runs, note: `${data.summary.failure_rate}% failure rate across terminal runs`, icon: AlertTriangle },
    ]
  }, [data])

  if (!projectId) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-sm text-[var(--text-secondary)]">
        Select a project to open its Kanban board.
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-[radial-gradient(circle_at_top_left,rgba(28,48,90,0.26),transparent_35%),linear-gradient(180deg,#0c111c,#0a0f18_48%,#0b1019)] text-white">
      <div className="border-b border-white/8 px-6 py-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="text-[11px] uppercase tracking-[0.22em] text-[var(--text-secondary)]">Project Execution Board</div>
            <h1 className="mt-2 text-2xl font-semibold">{data?.project.name || 'Kanban'}</h1>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-[var(--text-secondary)]">
              Real pipeline runs grouped by live status. Open any card to inspect the conversation, warnings, approvals, and artifacts behind that run.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <div className="rounded-full border border-white/8 bg-white/5 px-3 py-2 text-xs text-[var(--text-secondary)]">
              Updated {data ? formatRelativeChatTime(data.generated_at) : 'just now'}
            </div>
            <Button onClick={() => void load()} disabled={loading}>
              {loading ? <LoaderCircle className="mr-2 animate-spin" size={16} /> : <RefreshCw className="mr-2" size={16} />}
              Refresh
            </Button>
          </div>
        </div>
      </div>

      {error ? (
        <div className="m-6 rounded-2xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">
          {error}
        </div>
      ) : null}

      {loading && !data ? (
        <div className="flex flex-1 items-center justify-center text-sm text-[var(--text-secondary)]">Loading Kanban board…</div>
      ) : null}

      {data ? (
        <>
          <div className="grid grid-cols-1 gap-4 px-6 py-5 md:grid-cols-2 xl:grid-cols-4">
            {summaryCards.map((card) => (
              <SummaryCard key={card.label} label={card.label} value={card.value} note={card.note} icon={card.icon} />
            ))}
          </div>

          <div className="flex min-h-0 flex-1 gap-4 overflow-x-auto px-6 pb-6">
            {data.columns.map((column) => (
              <Column key={column.id} column={column} />
            ))}
          </div>
        </>
      ) : null}
    </div>
  )
}
