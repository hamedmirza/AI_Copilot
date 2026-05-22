# E2E Runs UX — Manual Verification Seed

## Purpose
Guide operators through end-to-end manual verification of the Runs UI, ensuring correct data flow, real-time updates, and interaction states.

## Prerequisites
- Backend running (`scripts/server.sh`)
- Frontend running (Vite dev server)
- Valid run executed in the workbench (triggers `/ws/runs/{id}` and `/ws/events`)

## Verification Steps

### 1. Run List & Status Display
- [ ] Navigate to the run history view (`frontend/src/components/AgentPanel/RunHistoryList.tsx`).
- [ ] Confirm runs are listed with statuses matching `frontend/src/types/runs.ts` (`RunStatus`).
- [ ] Verify `runStatusLabel()` maps status values to human-readable strings.

### 2. Real-Time WebSocket Updates
- [ ] Trigger a new run or modify an existing one.
- [ ] Observe the direct WebSocket connection to `/ws/runs/{id}`.
- [ ] Confirm UI updates synchronously without full page reloads.
- [ ] Check `frontend/src/hooks/useWebSocket.ts` for proper message handling and reconnection logic.

### 3. Terminal & PTY Integration
- [ ] Open the terminal panel (`frontend/src/components/Terminal/TerminalPanel.tsx`).
- [ ] Verify real-time output streaming via `/ws/events`.
- [ ] Confirm PTY input/output works bidirectionally without latency or disconnects.

### 4. Run Detail & History Navigation
- [ ] Click a run to open the detail drawer (`frontend/src/components/AgentPanel/RunDetailDrawer.tsx`).
- [ ] Validate tool calls (`ToolCallCard`), thinking indicators (`ThinkingIndicator`), and follow-up cards render correctly.
- [ ] Verify `frontend/src/components/shared/RunLogPanel.tsx` displays the full execution log.

### 5. Workspace & Directory Selection
- [ ] Trigger a workspace reset or folder picker.
- [ ] Confirm `pick_directory` is routed in a thread pool with a 120s timeout (per `COMPREHENSIVE_RULES_AND_GUIDELINES.md` §4).
- [ ] Verify the real Finder/dialog opens on macOS (automated tests monkeypatch native dialogs per `AGENTS.md` Manual verification section).

## Reporting Results
Document pass/fail status for each step and attach screenshots/logs to the corresponding [TASK_VERIFICATION_TEMPLATE.md](docs/TASK_VERIFICATION_TEMPLATE.md) entry. Follow [VERIFICATION_RULES.md](docs/VERIFICATION_RULES.md) for sign-off and DB/schema implications.