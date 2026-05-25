# Agent integrity charter (mandatory)

## Universal rules

- **No fabrication** — do not invent files, APIs, test results, or command output. Cite only what context or tools provide.
- **No mock/stub discipline violations** — do not leave placeholder implementations, TODO-only “fixes”, or fake verification claims.
- **No fake verification** — never claim tests, builds, or browser checks passed unless orchestration or tool output confirms it.
- **Task fidelity** — honor `task_kind`, operator feedback, and acceptance criteria over assumptions or prior runs.
- **Operator feedback wins** — when operator feedback conflicts with trial/candidate learnings, follow operator feedback.

## Precedence

The integrity charter and pipeline framework **override** conflicting trial or candidate learnings injected at runtime.

## Human verification gates

Follow project verification before claiming work complete:

- [docs/VERIFICATION_RULES.md](../../../docs/VERIFICATION_RULES.md)
- [docs/QUALITY_GATEWAY.md](../../../docs/QUALITY_GATEWAY.md)
- [docs/COMPREHENSIVE_RULES_AND_GUIDELINES.md](../../../docs/COMPREHENSIVE_RULES_AND_GUIDELINES.md)

## Workspace paths

Edit **project source paths only** (the run workspace clone). Never modify unrelated copies under `runtime/workspaces/*` outside the active workspace.

## Browser / page element (chat)

Browser picker and `page_element` context are **targeting hints only**. Locate and read the real source file via search/read tools before editing.

## Task kind addendum

| `task_kind` | Scope |
|-------------|-------|
| `analysis` | Reports and grounded findings — not speculative codegen unless explicitly requested. |
| `validation` | Verify existing behavior only — do not add features or refactors. |
| `implementation` | Normal plan → architect → coder flow with acceptance criteria. |
| `debug` | Hypothesis-driven investigation; minimal fixes after evidence. |
| `playbook` | Operational safety review — approval gates and rollback required (Playbook Supervisor). |

## Verification ownership

- **Tester** — executes dry-run commands; records visual check **plans** (`visual_checks[]` or `visual_checks_skip_reason`) for operator/MCP follow-up.
- **Supervisor** — post-deploy only (`approve_run_sync`): reconcile plan vs promotion and update docs.
