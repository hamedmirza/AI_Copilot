import type { RunThreadEntry } from '@/types/runs'

export function normalizeThreadEntry(row: Record<string, unknown>): RunThreadEntry {
  return {
    id: Number(row.id),
    run_id: String(row.run_id || ''),
    session_id: row.session_id != null ? String(row.session_id) : null,
    role: String(row.role || 'assistant'),
    entry_type: String(row.entry_type || ''),
    stage: row.stage != null ? String(row.stage) : null,
    severity: row.severity != null ? String(row.severity) : undefined,
    message: String(row.message || ''),
    payload: row.payload && typeof row.payload === 'object'
      ? row.payload as Record<string, unknown>
      : undefined,
    created_at: String(row.created_at || ''),
  }
}
