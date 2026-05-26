# Task Verification Template

Copy this section into a PR description, change request, or task note.

---

## Task

**ID / title:**  
**Date:**  
**Agent / author:**

## Scope

- Files changed:
- User-visible behavior:

## Automated checks

| Check | Command | Result |
|-------|---------|--------|
| Backend tests | `cd backend && .venv/bin/pytest` | ☐ pass |
| Frontend build | `npm --prefix frontend run build` | ☐ pass / N/A |
| Lint | `npm --prefix frontend run lint` | ☐ pass / N/A |

## Manual verification (if applicable)

| Step | Expected | Result |
|------|----------|--------|
| Server start | `./scripts/server.sh start-all` → health 200 | ☐ |
| UI smoke | http://localhost:5177 loads | ☐ |
| Feature-specific | (describe) | ☐ |

### Runs UI manual matrix (live progress)

| Check | Steps | Result |
|-------|--------|--------|
| Live progress | Start a run → open Runs drawer Pipeline tab → activity feed updates within ~2s on `pipeline_tool_*` and stage changes without refresh | ☐ |
| No false frozen | During 2+ min coder LLM, confirm heartbeat or "Still working…" line appears | ☐ |
| Post-run clean | After `run_completed`, feed collapses to summary; completed run does not show "No updates yet" | ☐ |
| Chat card | Spawn run from chat → RunCard shows live subtitle / activity | ☐ |
| Five-pass gate | Per [VERIFICATION_RULES.md](VERIFICATION_RULES.md): Missed / Fabricated / Violated / Skipped / Mock — all **no** before claiming done | ☐ |

## Notes

- Blockers:
- Follow-ups:

## Sign-off

- [ ] Matches [VERIFICATION_RULES.md](VERIFICATION_RULES.md)
- [ ] Passes [QUALITY_GATEWAY.md](QUALITY_GATEWAY.md)
