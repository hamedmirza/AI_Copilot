# Cursor Execution Guide

Agents working in this repo must follow these documents **before** marking any task complete.

## Required reading (in order)

1. **[AGENTS.md](AGENTS.md)** — stack, layout, dev commands, conventions
2. **[docs/COMPREHENSIVE_RULES_AND_GUIDELINES.md](docs/COMPREHENSIVE_RULES_AND_GUIDELINES.md)** — coding and review standards
3. **[docs/VERIFICATION_RULES.md](docs/VERIFICATION_RULES.md)** — what to verify and how
4. **[docs/QUALITY_GATEWAY.md](docs/QUALITY_GATEWAY.md)** — pass/fail gates before completion
5. **[docs/TASK_VERIFICATION_TEMPLATE.md](docs/TASK_VERIFICATION_TEMPLATE.md)** — fill for each non-trivial task

## Quick checklist

- [ ] Read relevant existing code before editing
- [ ] Run affected tests (`backend/.venv/bin/pytest` from `backend/`)
- [ ] Run `npm --prefix frontend run build` if frontend changed
- [ ] No unrelated refactors; match repo conventions
- [ ] Document manual steps if automation cannot cover them (e.g. macOS Finder Browse)

## Project rules file

Cursor also loads **[.cursorrules](.cursorrules)** for inline guidance.
