---
name: bmad-loop-pi
description: >
  Set up bmad-loop (the BMAD unattended dev/review/sweep orchestrator) to
  drive the pi coding agent as its coding CLI in a project. Use when the
  user asks to "configure bmad-loop for pi", "make bmad-loop use the pi
  agent", "install the bmad-loop pi adapter", or to re-run/upgrade that
  setup in a new project. The full procedure lives in this file; deep
  material (seam-drift audit, troubleshooting) is in sibling references/
  files — read them only when the situation calls for them. Prerequisites
  on the host: BMAD installed in the target project (a _bmad/ dir), pi on
  PATH, uv on PATH.
---

# bmad-loop ↔ pi adapter setup

bmad-loop (≤ 0.13.2) has **no built-in `pi` profile**. This skill installs
the bundled out-of-tree adapter (self-hosted print-mode transport: one
`pi -p` process per session; completion via process exit + pi's session
JSONL; `--approve` required; no stall nudges, no TUI attach) and wires the
project to it. Reference implementation seam-verified on bmad-loop 0.13.2 +
pi 1.2.0 — a version bump requires the audit in
`references/seam-drift-audit.md`, NOT blind re-runs. Resolve every
`assets/...` / `references/...` path against this skill's directory.

## Quick path (the 90% case: first-time setup, no version drift)

**0 — Upstream check (30 s).** `bmad-loop init --project <project> --cli pi`
on the *installed* bmad-loop. If `pi` now appears in the available profiles,
**stop**: upstream absorbed it — use the native profile and delete
`<project>/.bmad-loop/profiles/pi.toml` afterwards. If it says
`unknown CLI profile: 'pi'`, continue.

**1 — Preflight.** `uv --version`, `pi` on PATH (on Windows a bin dir
holding `pi` + `pi.cmd` is NORMAL — the adapter handles it; never "fix"
that), `_bmad/` exists in the target project, and provider auth is done
(`pi auth` — spawned sessions can't answer it). Missing pieces: install
uv per astral.sh docs; install pi-coding-agent; without `_bmad/` stop —
bmad-loop needs a BMAD install (BMAD-METHOD ≥ 6.10, bmm module).

**2 — Install / upgrade the toolchain.**

```sh
uv tool install "bmad-loop[tui] @ git+https://github.com/bmad-code-org/bmad-loop.git" \
  --with "<this-skill>/assets/adapter-pkg"
```

Pin a release tag with `@v<X.Y.Z>` for reproducibility. Then `bmad-loop adapters`
must show a `pi external no` row (missing → read the entry-point load
warning before anything else).

**3 — Project wiring.**

```sh
mkdir -p "<project>/.bmad-loop/profiles"
cp "<this-skill>/assets/pi-profile.toml" "<project>/.bmad-loop/profiles/pi.toml"
bmad-loop init --project "<project>" --cli pi
# set in <project>/.bmad-loop/policy.toml:  [adapter] name = "pi"
```

**4 — Validate.** `bmad-loop validate --project <project>` must show
`pi found` / `pi: adapter kind 'pi' registered` / all four stages
`dev=pi, review=pi, triage=pi, retro=pi`. The two **expected** FAILs:
`sprint status file not found` (run `bmad-sprint-planning` first) and
`git worktree is not clean` (commit/stash first; never auto-commit).
Any OTHER fail → `references/troubleshooting.md`.

**5 — Smoke (optional, one cheap pi turn).**

```sh
uv tool run --from bmad-loop python "<this-skill>/assets/smoke.py" "<project>"
```

Baseline (0.13.2): `status: stalled` + `stop_seen: True` + nonzero
TokenUsage + `hello.txt: OK`. `crashed` → read
`<project>/tmp/bmad-loop-pi-smoke/run/logs/smoke-1.pi.err`.

**6 — Hand-off.** Report versions, validate result, that `bmad-loop run`
is ready once the two expected FAILs are cleared, and the runtime
reminders (auto-commit behavior, token spend, no-nudges by design) —
the full checklist is in `references/troubleshooting.md` § Run-time.

## When something is off

- Any unexpected `bmad-loop adapters` / `validate` / run-start error,
  PATH trouble, or a multi-version-gap upgrade →
  **`references/troubleshooting.md`** (symptom → cause → fix).
- After ANY bmad-loop or pi version bump, before trusting the adapter →
  **`references/seam-drift-audit.md`** (seven seams to verify; patch the
  assets in place; re-run the no-LLM suite; re-derive smoke expectations).

## No-LLM unit suite (run before/after patching)

```sh
uv tool run --from bmad-loop python "<this-skill>/assets/adapter-pkg/tests/test_pi_adapter.py"
```

Deterministic, stdlib-only. The dev-synthesis test is a versioned canary:
if it fails after a bump, that is seam drift — do the audit, don't
re-baseline silently.

## Other agent harnesses

The skill's docs are harness-neutral and the adapter package is plain
Python; only the *skill file itself* is agent-skills-standard. Copy the
whole folder into any harness's skills dir (Claude Code / Codex / Gemini /
Copilot: `.claude/skills/`, `.agents/skills/`, `~/.agents/skills/`; pi:
`~/.pi/agent/skills/`) and the same procedure works.
