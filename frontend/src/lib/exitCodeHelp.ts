export interface ExitCodeHelp {
  label: string
  hint: string
}

const EXIT_MESSAGE_RE = /^exit=(\d+)$/

const EXIT_HELP: Record<number, ExitCodeHelp> = {
  0: { label: 'Success', hint: 'No action needed.' },
  1: {
    label: 'Tests or script failed',
    hint: 'Read stderr in the log and fix the failing assertion or error.',
  },
  2: {
    label: 'Shell syntax error',
    hint: 'Fix quoting or flags in the pipeline test command.',
  },
  126: {
    label: 'Command not executable',
    hint: 'chmod +x the binary or run it via python/bash explicitly.',
  },
  127: {
    label: 'Command not found',
    hint: 'Use project venv paths (e.g. backend/.venv/bin/pytest), not bare pytest.',
  },
  128: {
    label: 'Invalid exit status',
    hint: 'Fix the script that called exit; the child status was invalid.',
  },
  130: {
    label: 'Interrupted',
    hint: 'Re-run the step; the process was cancelled (Ctrl+C or stop).',
  },
  137: {
    label: 'Process killed',
    hint: 'Check OOM or kill -9; split work or reduce command scope.',
  },
  143: {
    label: 'Process terminated',
    hint: 'Check step timeouts or whether the dev server was stopped.',
  },
}

const SIGNAL_NAMES: Record<number, string> = {
  1: 'SIGHUP',
  2: 'SIGINT',
  9: 'SIGKILL',
  15: 'SIGTERM',
}

export function parseExitCodeFromMessage(message: string): number | null {
  const match = message.trim().match(EXIT_MESSAGE_RE)
  return match ? Number(match[1]) : null
}

export function getExitCodeHelp(code: number): ExitCodeHelp {
  const known = EXIT_HELP[code]
  if (known) return known

  if (code > 128 && code < 192) {
    const signal = code - 128
    const name = SIGNAL_NAMES[signal]
    return {
      label: name ? `Stopped by ${name}` : `Stopped by signal ${signal}`,
      hint: 'Check timeouts, manual stop, or retry the pipeline step.',
    }
  }

  if (code >= 3 && code <= 125) {
    return {
      label: 'Command failed',
      hint: 'Expand the log stderr above and fix the reported failure.',
    }
  }

  return {
    label: `Exit ${code}`,
    hint: 'Inspect stderr in the log for the underlying failure.',
  }
}

/** One-line summary for monospace activity log rows. */
export function formatExitMessage(message: string): string {
  const code = parseExitCodeFromMessage(message)
  if (code === null) return message
  const { label, hint } = getExitCodeHelp(code)
  if (code === 0) return message
  return `${label} (${code}) — ${hint}`
}
