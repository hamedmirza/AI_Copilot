# Pipeline collaboration framework

Downstream agents reject with **fix instructions**; upstream agents read downstream expectations **before** emitting output. Deterministic guards are safety nets — not substitutes for reading this framework.

## Stage contract

| Stage | Produces | Downstream checks |
|-------|----------|-------------------|
| **Planner** | `steps[]` + `acceptance_criteria[]` per step | Architect, Coder, and Reviewer map work to criteria |
| **Architect** | `file_changes[]` blueprint (paths + rationale) | Coder stays in blueprint scope; Reviewer checks coverage |
| **UI Designer** | component spec (`layout_description`, `components[]`) | Reviewer checks frontend edits when UI work is present |
| **Coder** | surgical patches (`line_changes` preferred) | Reviewer + structural guards + frontend `tsc` |
| **Reviewer** | approve/reject with file + criterion citations | Must cite blueprint/criteria; no vague blocks |
| **Tester** | `dry_run_steps[]` (canonical frontend cmds), executed `visual_evidence`, extra `commands[]` | Dry-run + build pass; visual capture required for UI |
| **Supervisor** | pre-deploy gate + post-deploy `plan_gaps[]` | Pre-deploy blocks approval; post-deploy runs in `approve_run_sync` |

## Collaboration rules

1. **Planner → Architect:** each step needs measurable acceptance criteria; architect paths must trace to criteria.
2. **Architect → Coder:** coder reads blueprint paths and criteria before patching; no drive-by files.
3. **UI Designer → Coder/Reviewer:** frontend TSX edits should align with UI spec when UI stage ran.
4. **Coder → Reviewer:** reviewer receives before/after snapshots and diff; rejects with actionable fixes.
5. **Reviewer → Coder retry:** coder applies reviewer/guard guidance exactly on retry — do not re-litigate scope.
6. **Tester:** canonical frontend dry-run (`tsc.js` + `npm --prefix frontend run build`); captures `visual_evidence`; integration/contract gates must pass.
7. **Pre-deploy supervisor:** compares plan vs workspace; blocks if `approved: false` or critical gaps.
8. **Post-deploy supervisor:** after operator approve/promote — doc reconciliation only.

## Handoff quality bar

- Rejections name **file**, **criterion or blueprint path**, and **concrete fix**.
- Approvals mean safe to proceed — not “perfect style”.
- Protected files are never patch targets; planner/architect must route around them.
