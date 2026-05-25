import { ArrowUpRight, BriefcaseBusiness, CalendarRange, CheckCircle2, CircleDashed, Clock3, Flame, Layers3, MessageSquareText, Plus, Sparkles, Target } from 'lucide-react'

type Card = {
  id: string
  title: string
  summary: string
  owner: string
  due: string
  priority: 'Critical' | 'High' | 'Medium' | 'Low'
  tags: string[]
  comments: number
}

type Column = {
  id: string
  title: string
  caption: string
  accent: string
  cards: Card[]
}

const columns: Column[] = [
  {
    id: 'backlog',
    title: 'Backlog',
    caption: 'Qualified work ready for planning',
    accent: 'from-slate-500/35 via-slate-400/10 to-transparent',
    cards: [
      {
        id: 'AC-118',
        title: 'Unify run recovery timeline',
        summary: 'Consolidate failure state breadcrumbs so operators can reason about retries without opening raw logs.',
        owner: 'Maya',
        due: 'May 28',
        priority: 'High',
        tags: ['Runtime', 'UX'],
        comments: 6,
      },
      {
        id: 'AC-121',
        title: 'Provider comparison snapshots',
        summary: 'Capture latency, tool support, and context-window deltas in a single review surface.',
        owner: 'Noah',
        due: 'Jun 1',
        priority: 'Medium',
        tags: ['Models', 'Metrics'],
        comments: 3,
      },
    ],
  },
  {
    id: 'progress',
    title: 'In Progress',
    caption: 'Active execution with defined owners',
    accent: 'from-cyan-500/35 via-cyan-400/10 to-transparent',
    cards: [
      {
        id: 'AC-109',
        title: 'Operator-grade Kanban workspace',
        summary: 'Introduce a clean delivery board with portfolio summary, clear status grouping, and fast scan hierarchy.',
        owner: 'Iris',
        due: 'Today',
        priority: 'Critical',
        tags: ['Frontend', 'Design'],
        comments: 11,
      },
      {
        id: 'AC-116',
        title: 'Terminal reconnect diagnostics',
        summary: 'Expose PTY handshake state and recent reconnect attempts directly in the workbench.',
        owner: 'Theo',
        due: 'May 30',
        priority: 'High',
        tags: ['Terminal', 'Debugging'],
        comments: 4,
      },
    ],
  },
  {
    id: 'review',
    title: 'Review',
    caption: 'Ready for sign-off and QA',
    accent: 'from-amber-500/35 via-amber-400/10 to-transparent',
    cards: [
      {
        id: 'AC-103',
        title: 'Refine project intake wizard',
        summary: 'Tighten copy, validation feedback, and browse-path handling for local project imports.',
        owner: 'Lena',
        due: 'May 27',
        priority: 'Medium',
        tags: ['Onboarding', 'Validation'],
        comments: 8,
      },
    ],
  },
  {
    id: 'done',
    title: 'Done',
    caption: 'Delivered and verified',
    accent: 'from-emerald-500/35 via-emerald-400/10 to-transparent',
    cards: [
      {
        id: 'AC-097',
        title: 'Stabilize browser picker shortcuts',
        summary: 'Resolve dev-mode shortcut clashes and preserve element-selection flow across remounts.',
        owner: 'Jules',
        due: 'May 24',
        priority: 'Low',
        tags: ['Browser', 'Polish'],
        comments: 2,
      },
    ],
  },
]

const priorityStyles: Record<Card['priority'], string> = {
  Critical: 'bg-rose-500/12 text-rose-200 ring-1 ring-rose-400/30',
  High: 'bg-amber-500/12 text-amber-100 ring-1 ring-amber-400/30',
  Medium: 'bg-cyan-500/12 text-cyan-100 ring-1 ring-cyan-400/30',
  Low: 'bg-emerald-500/12 text-emerald-100 ring-1 ring-emerald-400/30',
}

const totalCards = columns.reduce((sum, column) => sum + column.cards.length, 0)
const inFlightCards = columns
  .filter((column) => column.id === 'progress' || column.id === 'review')
  .reduce((sum, column) => sum + column.cards.length, 0)

function StatCard({
  icon: Icon,
  label,
  value,
  detail,
}: {
  icon: typeof Target
  label: string
  value: string
  detail: string
}) {
  return (
    <div className="rounded-2xl border border-white/8 bg-white/4 p-4 shadow-[0_18px_40px_rgba(0,0,0,0.24)] backdrop-blur-sm">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-semibold uppercase tracking-[0.22em] text-[var(--text-secondary)]">
          {label}
        </span>
        <span className="rounded-full border border-white/10 bg-black/20 p-2 text-cyan-200">
          <Icon size={16} />
        </span>
      </div>
      <div className="mt-4 text-2xl font-semibold text-white">{value}</div>
      <div className="mt-1 text-sm text-[var(--text-secondary)]">{detail}</div>
    </div>
  )
}

function KanbanCard({ card }: { card: Card }) {
  return (
    <article className="group rounded-2xl border border-white/8 bg-[#14181f]/92 p-4 shadow-[0_20px_45px_rgba(0,0,0,0.35)] transition duration-200 hover:-translate-y-0.5 hover:border-cyan-400/30 hover:bg-[#171d26]">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-cyan-200/80">{card.id}</div>
          <h3 className="mt-2 text-sm font-semibold text-white">{card.title}</h3>
        </div>
        <button className="rounded-full border border-white/8 bg-white/4 p-2 text-[var(--text-secondary)] transition group-hover:text-white">
          <ArrowUpRight size={14} />
        </button>
      </div>
      <p className="mt-3 text-sm leading-6 text-[var(--text-secondary)]">{card.summary}</p>
      <div className="mt-4 flex flex-wrap gap-2">
        <span className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${priorityStyles[card.priority]}`}>
          {card.priority}
        </span>
        {card.tags.map((tag) => (
          <span key={tag} className="rounded-full border border-white/10 bg-white/4 px-2.5 py-1 text-[11px] text-slate-200">
            {tag}
          </span>
        ))}
      </div>
      <div className="mt-4 flex items-center justify-between border-t border-white/8 pt-4 text-xs text-[var(--text-secondary)]">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-cyan-300 to-blue-500 text-[11px] font-semibold text-slate-950">
            {card.owner.slice(0, 2).toUpperCase()}
          </div>
          <div>
            <div className="text-white">{card.owner}</div>
            <div>{card.due}</div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span className="inline-flex items-center gap-1">
            <CalendarRange size={13} />
            {card.due}
          </span>
          <span className="inline-flex items-center gap-1">
            <MessageSquareText size={13} />
            {card.comments}
          </span>
        </div>
      </div>
    </article>
  )
}

export function KanbanBoard() {
  return (
    <div className="h-full overflow-auto bg-[radial-gradient(circle_at_top_left,rgba(34,211,238,0.18),transparent_28%),radial-gradient(circle_at_top_right,rgba(59,130,246,0.16),transparent_24%),linear-gradient(180deg,#0b0e13_0%,#10141b_48%,#0d1016_100%)]">
      <div className="mx-auto flex min-h-full max-w-[1680px] flex-col gap-6 px-6 py-6">
        <section className="relative overflow-hidden rounded-[28px] border border-white/8 bg-[linear-gradient(135deg,rgba(255,255,255,0.08),rgba(255,255,255,0.02))] p-6 shadow-[0_30px_80px_rgba(0,0,0,0.35)]">
          <div className="absolute inset-y-0 right-0 hidden w-80 bg-[radial-gradient(circle_at_center,rgba(255,255,255,0.12),transparent_70%)] lg:block" />
          <div className="relative flex flex-col gap-6 xl:flex-row xl:items-end xl:justify-between">
            <div className="max-w-3xl">
              <div className="inline-flex items-center gap-2 rounded-full border border-cyan-300/15 bg-cyan-300/8 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.22em] text-cyan-100">
                <Sparkles size={14} />
                Delivery board
              </div>
              <h1 className="mt-4 max-w-2xl text-3xl font-semibold tracking-tight text-white md:text-4xl">
                Kanban workspace for focused execution and clean operator visibility.
              </h1>
              <p className="mt-3 max-w-2xl text-sm leading-7 text-slate-300">
                A polished board for planning, active work, review, and verified delivery. The layout emphasizes fast scanning, ownership, and milestone clarity inside the IDE shell.
              </p>
            </div>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:min-w-[620px]">
              <StatCard icon={Layers3} label="Total items" value={String(totalCards)} detail="Across the current sprint board" />
              <StatCard icon={Flame} label="In flight" value={String(inFlightCards)} detail="Actively moving toward release" />
              <StatCard icon={Clock3} label="Cycle time" value="3.4d" detail="Average from start to verification" />
              <StatCard icon={CheckCircle2} label="Done rate" value="91%" detail="Tasks closed with QA evidence" />
            </div>
          </div>
        </section>

        <section className="grid gap-4 lg:grid-cols-[1.4fr_0.9fr_0.9fr]">
          <div className="rounded-2xl border border-white/8 bg-[#11161d]/92 p-5 shadow-[0_18px_40px_rgba(0,0,0,0.28)]">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-[var(--text-secondary)]">Sprint health</div>
                <div className="mt-2 text-lg font-semibold text-white">Execution is stable, but review is the current bottleneck.</div>
              </div>
              <div className="rounded-full border border-emerald-400/20 bg-emerald-400/10 px-3 py-1 text-xs font-medium text-emerald-100">
                On track
              </div>
            </div>
            <div className="mt-4 h-2 overflow-hidden rounded-full bg-white/6">
              <div className="h-full w-[72%] rounded-full bg-[linear-gradient(90deg,#22d3ee_0%,#60a5fa_55%,#34d399_100%)]" />
            </div>
            <div className="mt-3 grid gap-3 text-sm text-slate-300 md:grid-cols-3">
              <div className="rounded-xl border border-white/6 bg-white/4 p-3">
                <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--text-secondary)]">Priority lane</div>
                <div className="mt-1 text-white">In Progress</div>
              </div>
              <div className="rounded-xl border border-white/6 bg-white/4 p-3">
                <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--text-secondary)]">Risk</div>
                <div className="mt-1 text-white">Design review capacity</div>
              </div>
              <div className="rounded-xl border border-white/6 bg-white/4 p-3">
                <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--text-secondary)]">Next milestone</div>
                <div className="mt-1 text-white">Internal demo on May 28</div>
              </div>
            </div>
          </div>

          <div className="rounded-2xl border border-white/8 bg-[#11161d]/92 p-5 shadow-[0_18px_40px_rgba(0,0,0,0.28)]">
            <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.2em] text-[var(--text-secondary)]">
              <CircleDashed size={14} />
              Workload
            </div>
            <div className="mt-4 space-y-3">
              {columns.map((column) => (
                <div key={column.id}>
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-white">{column.title}</span>
                    <span className="text-[var(--text-secondary)]">{column.cards.length} items</span>
                  </div>
                  <div className="mt-2 h-2 overflow-hidden rounded-full bg-white/6">
                    <div
                      className="h-full rounded-full bg-[linear-gradient(90deg,#22d3ee_0%,#60a5fa_100%)]"
                      style={{ width: `${Math.max(12, (column.cards.length / totalCards) * 100)}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-2xl border border-white/8 bg-[#11161d]/92 p-5 shadow-[0_18px_40px_rgba(0,0,0,0.28)]">
            <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.2em] text-[var(--text-secondary)]">
              <BriefcaseBusiness size={14} />
              Team focus
            </div>
            <div className="mt-4 space-y-3 text-sm">
              <div className="rounded-xl border border-white/6 bg-white/4 p-3 text-slate-300">
                Keep review columns small to preserve merge confidence and shorten operator validation time.
              </div>
              <div className="rounded-xl border border-white/6 bg-white/4 p-3 text-slate-300">
                Pair frontend design tasks with acceptance evidence so visual changes do not regress runtime workflows.
              </div>
              <button className="inline-flex items-center gap-2 rounded-xl border border-cyan-300/20 bg-cyan-300/10 px-3 py-2 text-sm font-medium text-cyan-50 transition hover:bg-cyan-300/16">
                <Plus size={15} />
                Add work item
              </button>
            </div>
          </div>
        </section>

        <section className="grid min-w-[980px] grid-cols-4 gap-5 pb-4">
          {columns.map((column) => (
            <div key={column.id} className="rounded-[24px] border border-white/8 bg-[#0f1319]/88 p-4 shadow-[0_20px_50px_rgba(0,0,0,0.3)]">
              <div className={`rounded-2xl bg-gradient-to-r ${column.accent} p-[1px]`}>
                <div className="rounded-2xl bg-[#11161d]/96 px-4 py-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="text-sm font-semibold text-white">{column.title}</div>
                      <div className="mt-1 text-xs leading-5 text-[var(--text-secondary)]">{column.caption}</div>
                    </div>
                    <div className="rounded-full border border-white/10 bg-white/4 px-2.5 py-1 text-xs text-slate-200">
                      {column.cards.length}
                    </div>
                  </div>
                </div>
              </div>
              <div className="mt-4 space-y-4">
                {column.cards.map((card) => (
                  <KanbanCard key={card.id} card={card} />
                ))}
              </div>
            </div>
          ))}
        </section>
      </div>
    </div>
  )
}
