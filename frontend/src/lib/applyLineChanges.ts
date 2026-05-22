/** Mirror of backend patch_guard.apply_line_changes for client-side diff preview. */
function splitLinesKeepEnds(content: string): string[] {
  const lines = content.split(/(?<=\n)/)
  if (!lines.length && content) return [content]
  if (!lines.length) return ['']
  return lines
}

export function applyLineChanges(
  content: string,
  lineChanges: Array<{ start_line: number; end_line: number; new_content: string }>,
): string {
  let lines = splitLinesKeepEnds(content)

  const sorted = [...lineChanges].sort((a, b) => b.start_line - a.start_line)
  for (const change of sorted) {
    const start = Math.max(1, change.start_line) - 1
    const end = Math.max(start, change.end_line - 1)
    let newContent = change.new_content ?? ''
    let newLines = newContent.split(/\n/)
    if (newLines.length > 1 || newContent.includes('\n')) {
      newLines = newContent.split(/\n/).map((line, i, arr) =>
        i < arr.length - 1 ? `${line}\n` : line,
      )
    }
    if (newContent && !newContent.endsWith('\n') && content.includes('\n') && newLines.length) {
      const last = newLines[newLines.length - 1]
      if (!last.endsWith('\n')) newLines[newLines.length - 1] = `${last}\n`
    }
    lines.splice(start, end - start + 1, ...newLines)
  }
  return lines.join('')
}
