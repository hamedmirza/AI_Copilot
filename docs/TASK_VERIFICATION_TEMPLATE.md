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

## Notes

- Blockers:
- Follow-ups:

## Sign-off

- [ ] Matches [VERIFICATION_RULES.md](VERIFICATION_RULES.md)
- [ ] Passes [QUALITY_GATEWAY.md](QUALITY_GATEWAY.md)
