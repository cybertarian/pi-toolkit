# Troubleshooting (bmad-loop × pi adapter)

Symptom → cause → fix. Production-verified on this class of machine
(Windows + pi managed install + uv tool environments, 2026-12).

## Setup-time

| Symptom | Cause | Fix |
|---|---|---|
| `bmad-loop adapters` has no `pi` row | The `--with` build of the adapter package failed, or its entry point failed to import | Read the warning `bmad-loop adapters` prints (it names failed loads); re-run SKILL.md §2 install; `uv tool install --reinstall` if the wheel looks stale |
| `FAIL: unknown CLI profile: 'pi'` at `init` | The project profile is missing OR upstream absorbed pi natively | If `pi` now appears in the available-profiles list → use the native one and delete the project's `pi.toml`. Otherwise re-copy `assets/pi-profile.toml` to `.bmad-loop/profiles/pi.toml` |
| `validate` FAIL: `sprint status file not found` | Not a setup failure — `bmad-sprint-planning` hasn't run | Run it; then re-validate |
| `validate` FAIL: `git worktree is not clean` | Not a setup failure — pending changes | Commit/stash first; bmad-loop refuses to start on a dirty tree (never auto-commit for the user) |
| `validate` FAIL: `pi not found on PATH` | Session's PATH is stale or pi not installed | Refresh the running shell's PATH from the registry (Windows: `$env:Path = (Machine + ';' + User)`); install pi if truly absent |
| run start: `profile 'pi': adapter kind 'pi' rejected this run's adapter keywords` | **Seam drift** — a bmad-loop upgrade moved the build-kwargs contract | Run `references/seam-drift-audit.md`; patch `PiAdapter.__init__` |
| a dev/review session ends and the run pauses | A result-less turn end: the pi session finished without leaving a terminal story spec. By design there are no stall nudges in print mode | Re-drive (`bmad-loop resume`/resolve) or shorten the story scope; this is the expected degradation, not a crash |
| `crashed` verdicts with provider errors in the log tail | `pi auth` not done, or the provider is down | `pi auth` in the project; check the provider; a zero-token crash = the CLI never reached the API |

## PATH / environment (Windows)

- **Never `setx PATH …`** — it truncates to 1024 chars and silently
  deletes entries (real incident: a 1560-char user PATH lost 10 entries,
  incl. WindowsApps/pwsh and .dotnet/tools). Use
  `[Environment]::SetEnvironmentVariable('Path', $value,
  [System.EnvironmentVariableTarget]::User)` (PS argument order:
  name, value, target) or the OS GUI editor. Refresh running shells
  after the change.
- Modern Python's `shutil.which` does **not** match extensionless names
  on Windows — the adapter looks for `node.exe` first for that reason.
  If you patch binary resolution, keep that order and keep the tests
  (they pin the semantics hermetically).

## Multiplexers (only if you switch driver CLIs)

The pi adapter is self-hosted (`needs_mux=False`) — **psmux/tmux are not
needed for it**. They only matter when a stage runs a pane-family CLI
(claude/codex/copilot/antigravity): then install the `psmux` binary
≥ 3.3.9 (github.com/psmux/psmux release zip) + `pwsh` ≥ 7.3 on PATH, and
re-run `bmad-loop validate` (its psmux line names the missing helper).

## Run-time (`bmad-loop run` / `bmad-loop tui`)

- **It auto-commits.** verify-gate passing → one story commit on the
  current branch. Point it at a reviewable/rollback-able branch, or set
  `scm.isolation = "worktree"` so attempts stay off the main checkout.
- **It spends real tokens.** Budgets live in `.bmad-loop/policy.toml`
  (`max_tokens_per_session`, `session_budget_mode` …).
- **Long-running & unattended.** Trigger it from a terminal (or
  detached), monitor with `bmad-loop tui`; a pi chat / desktop-app
  shell that blocks on `bmad-loop run` will time out, not "watch" it.
- pi sessions run to their natural end or `limits.session_timeout_min`;
  transcripts land under `.bmad-loop/runs/<run>/pi-sessions/`, logs
  under `…/logs/` (both gitignored by `init`).

## Code-side sharp edges (if you patch the adapter)

- `dev_contract_nudge` is the policy attribute name (no trailing 's').
- `ProjectPaths.artifact_at` answers ONE Path, not a list (the dev
  mixin globs it) — the unit suite's fake `paths` must match.
- The Popen argv for pi must stay `[node, pi-launcher.js, …]` on the
  managed layout; passing the prompt through `cmd /c` batch quoting is a
  known hazard — do not "simplify" it back.
- Release the parent-side log file handles right after spawn (the child
  keeps its own kernel handles); otherwise long runs accumulate
  unclosed BufferedWriters.
