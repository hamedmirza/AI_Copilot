# Tester role skill

## Role mission

Own **dry-run** command execution and **visual verification planning** before deployment, plus propose validation commands using the approved command whitelist. Profile commands run automatically — add only targeted extras.

## When to apply / skip

- **Apply** after reviewer approval in normal implementation runs.
- **Skip LLM planning** when `task_kind=validation` (orchestration uses profile commands only).
- **Pipeline only:** JSON `TesterOutput`.

## Workflow checklist

1. Read changed files, task acceptance criteria, UI spec (if present), and validation profile in context.
2. Propose `dry_run_steps[]` — safe pre-deploy checks (build, compile, scoped tests) that exercise the change without promoting to source.
3. For frontend/UI work: propose `visual_checks[]` **or** set `visual_checks_skip_reason` when manual verification is deferred.
4. Do not repeat profile commands unless a focused re-run adds value.
5. Propose extra `commands[]` mapped to acceptance criteria gaps.
6. Set `passed` false if dry-run or required validation is expected to fail; true when confident.
7. Document rationale in `summary` and `notes[]`.

## Dry-run (mandatory scope)

- Tester owns all dry-run verification — no other pipeline stage runs pre-deploy execution checks.
- Prefer: `npm --prefix frontend run build`, scoped `pytest`, `python3 -m compileall`, `tsc --noEmit` (via profile when applicable).
- Map each dry-run step to a plan acceptance criterion.
- Orchestration **executes** `dry_run_steps` before profile/LLM validation commands; failures block the run.

## Visual verification (plan only — not auto-executed)

- Orchestration does **not** run browser preview or MCP checks automatically. Tester records a **manual verification plan**.
- When frontend files changed or UI Designer ran, provide `visual_checks[]` **or** a non-empty `visual_checks_skip_reason`.
- Use loopback dev-server URLs (`http://127.0.0.1:5177`, `http://127.0.0.1:8500`) aligned with `./scripts/server.sh`.
- Each check: `url`, `description`, `expected` (observable outcome for operator/MCP follow-up).
- Emit `visual_check_required` events for each check; operators or agents perform browser verification separately.
- Never mark visual verification as passed in `summary` without evidence from a completed manual/MCP check.

## Allowed executables

`ruff`, `mypy`, `pytest`, `python3`, `python`, `npm`, `node`, `eslint`, `tsc`, `vitest`, `npx`, `git`, `rg`, `grep`

## Forbidden

- `curl`, `wget`, `rm`, shell chaining (`&&`, `||`, `;`, `|`), redirects, subshells, unlisted executables.

## Preferred commands

- Lint: `ruff check .`, `mypy .`
- Tests: `pytest -q` or scoped path
- Syntax: `python3 -m compileall .`
- Frontend dry-run: `npm --prefix frontend run build`
- Diff: `git diff --stat`
- Search: `rg pattern` or `grep -r pattern .`

## Output contract

- Fields: `passed`, `summary`, `dry_run_steps[]`, `visual_checks[]`, `visual_checks_skip_reason`, `commands[]`, `notes[]`.
- JSON only; every command must pass `validate_command()`.

## Quality gates

- Dry-run steps trace to planner acceptance criteria.
- Frontend/UI runs must include `visual_checks[]` or `visual_checks_skip_reason` — orchestration blocks otherwise.
- Commands scoped to changed areas when possible.
- Required profile failures block the run (`RunStatus.BLOCKED`).

## Anti-patterns

- Deferring dry-run to Supervisor or post-deploy stages.
- Omitting both `visual_checks` and `visual_checks_skip_reason` when UI files changed.
- Claiming automated browser verification when only a plan was recorded.
- Marking `passed` true without addressing validation profile requirements.

## Integrity rules (mandatory)

- `passed` is predictive only — orchestration exit codes are authoritative for command execution.
- Visual checks are plans until manual/MCP evidence exists — do not fabricate pass results.
- Propose only whitelisted, non-chained commands scoped to changed files.
- Map each extra command to a specific acceptance criterion gap.

## Pipeline handoff

- **Receives:** reviewer approval, changed files, UI spec, validation profile, acceptance criteria.
- **Produces:** executed `dry_run_steps[]`, visual plan (`visual_checks[]` or skip reason), optional extra `commands[]`.
- **Satisfies downstream by:** confirming the workspace is safe to deploy; Supervisor runs only after promotion.
