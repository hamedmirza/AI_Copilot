export type RunComposerStatus =
  | 'pending'
  | 'running'
  | 'awaiting_clarification'
  | 'awaiting_approval'
  | 'changes_requested'
  | 'blocked'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | string

export interface RunComposerLabels {
  placeholder: string
  primaryLabel: string
  hint: string | null
  primaryDisabled: boolean
  showPrimary: boolean
}

export function runComposerLabels(status: RunComposerStatus): RunComposerLabels {
  switch (status) {
    case 'awaiting_clarification':
      return {
        placeholder: 'Answer with target surface (e.g. workbench, chat, activity bar)…',
        primaryLabel: 'Send answer',
        hint: null,
        primaryDisabled: false,
        showPrimary: true,
      }
    case 'awaiting_approval':
      return {
        placeholder: 'Optional note before approving…',
        primaryLabel: 'Approve run',
        hint: 'Opens the approval dialog with readiness checks.',
        primaryDisabled: false,
        showPrimary: true,
      }
    case 'changes_requested':
    case 'failed':
    case 'blocked':
      return {
        placeholder: 'Describe what to change on retry…',
        primaryLabel: 'Retry pipeline',
        hint: null,
        primaryDisabled: false,
        showPrimary: true,
      }
    case 'running':
      return {
        placeholder: 'Pipeline in progress…',
        primaryLabel: 'Pipeline in progress',
        hint: 'Wait for the current stage to finish.',
        primaryDisabled: true,
        showPrimary: false,
      }
    case 'completed':
      return {
        placeholder: 'Optional follow-up for a new attempt…',
        primaryLabel: 'Run again',
        hint: 'Submits feedback and re-queues the pipeline.',
        primaryDisabled: false,
        showPrimary: true,
      }
    default:
      return {
        placeholder: 'Message this run…',
        primaryLabel: 'Send',
        hint: null,
        primaryDisabled: true,
        showPrimary: false,
      }
  }
}
