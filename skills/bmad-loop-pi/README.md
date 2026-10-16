# bmad-loop-pi

> Originally published at [`cybertarian/bmad-loop-pi`](https://github.com/cybertarian/bmad-loop-pi); now maintained under the `skills/` directory of [pi-toolkit](https://github.com/cybertarian/pi-toolkit). Git history of the original single-purpose repo is not carried over here.

A shareable agent skill that sets up [bmad-loop](https://github.com/bmad-code-org/bmad-loop) — the BMAD unattended dev/review/sweep orchestrator — to drive the [pi coding agent](https://github.com/badlogic/pi) as its coding CLI.

bmad-loop 0.13.x has no built-in `pi` profile. Per the bmad-loop maintainers (bmad-code-org/bmad-loop#763), pi is not a planned official adapter — the sanctioned path is a community out-of-tree adapter, which is exactly what this skill installs, configures, and verifies for you.

## Table of Contents

- [How it works](#how-it-works)
- [What's inside](#whats-inside)
- [Requirements](#requirements)
- [Install](#install)
- [Usage](#usage)
- [Testing](#testing)
- [Upgrades & seam drift](#upgrades--seam-drift)
- [Troubleshooting](#troubleshooting)
- [Other agent harnesses](#other-agent-harnesses)
- [License](#license)

## How it works

In one pass, in any BMAD project:

1. Co-installs the bundled `bmad-loop-adapter-pi` package (MIT) into the bmad-loop uv environment — one `pi -p` process per orchestrator session; completion via process exit + pi's session-JSONL; token usage read from pi's session files.
2. Writes `.bmad-loop/profiles/pi.toml` and runs `bmad-loop init --cli pi`.
3. Points every policy stage (dev / review / triage / retro) at `pi`.
4. Runs `bmad-loop validate` and separates expected FAILs (missing sprint board, dirty worktree) from real problems.
5. Optionally runs a live wiring smoke (one cheap pi turn) and a no-LLM unit suite.

No terminal multiplexer needed (`needs_mux=False`): psmux/tmux only
matter if you later drive a pane-family CLI (claude/codex/…).

| Axis | Value | Meaning |
|---|---|---|
| injection | `launch-flag` | prompt on the command line (`pi -p … --approve --session-dir … --session-id …`) |
| observation | `transcript-poll` | process exit + session-JSONL + the skill's on-disk spec |
| state | `local-jsonl` | usage summed from pi's session file |

The dev/review variants compose bmad-loop's `_DevSynthesisMixin`, so a
story spec left on disk by the bmad-build-auto skill is synthesized into
the session result — the same contract the built-in families honor.

**Design consequences (not bugs):** no stall wake-nudges (a result-less
turn end pauses the run per policy), and the TUI shows logs rather than
a live pane.

## What's inside

```
SKILL.md                     the agent-facing procedure (thin router)
references/
  seam-drift-audit.md        the 7-seam upgrade audit (read only when versions move)
  troubleshooting.md         symptom → cause → fix, plus run-time safety notes
assets/
  adapter-pkg/               the bmad-loop-adapter-pi package (MIT)
    bmad_loop_adapter_pi/    PiAdapter (plain) + PiDevAdapter (dev/review)
    tests/                   no-LLM unit suite + deterministic fake-pi emulator
  pi-profile.toml            the .bmad-loop/profiles/pi.toml template
  smoke.py                   live wiring smoke (one cheap pi turn)
```

## Requirements

- A BMAD project (`_bmad/` present, BMAD-METHOD ≥ 6.10 with the bmm module)
- pi on PATH, provider auth done (`pi auth`)
- uv on PATH, Python 3.11+ (bmad-loop's floor)

## Install

Install the skill itself (Agent Skills / skills.sh ecosystem):

```sh
# now part of pi-toolkit (skills/bmad-loop-pi/); drop the folder into your
# agent's skills dir (pi: ~/.pi/agent/skills/bmad-loop-pi/)
# legacy: npx skills add cybertarian/bmad-loop-pi -g  (works until the old repo is archived)
```

Then invoke it per project:

```
/bmad-loop-pi <project-path>
```

or just ask: *"configure bmad-loop for pi in this project"*.

## Usage

```sh
# after the skill has set things up, in the project:
bmad-loop validate          # preflight
bmad-loop run              # start (needs a sprint board + clean worktree)
bmad-loop tui              # monitor
```

Run-time safety: bmad-loop **auto-commits** story work and spends real
tokens — pick a branch you can roll back (or set
`scm.isolation = "worktree"`), and monitor with the TUI rather than
blocking a chat shell on `bmad-loop run`. Details in
`references/troubleshooting.md` § Run-time.

## Testing

- **No-LLM unit suite** (deterministic, no provider, fast, stdlib-only):

  ```sh
  uv tool run --from bmad-loop python assets/adapter-pkg/tests/test_pi_adapter.py
  ```

- **Live wiring smoke** (one cheap pi turn; proves spawn → session file
  → usage parse → dev-mixin read-back → kill/evict):

  ```sh
  uv tool run --from bmad-loop python assets/smoke.py <project>
  ```

## Upgrades & seam drift

The bundled adapter is a *reference implementation*, not a pin. After
any bmad-loop or pi version bump: run the **seam-drift audit**
(`references/seam-drift-audit.md`) — seven seams to verify, patch
`assets/adapter-pkg` in place, rebuild, re-run the unit suite (the
dev-synthesis test is a versioned canary), re-derive smoke expectations.
The §0 upstream check also re-runs first: if bmad-loop ever absorbs pi
natively, the custom adapter retires automatically.

## Troubleshooting

Symptom → cause → fix table, including the expected `validate` FAILs
versus real failures, Windows PATH traps (`setx` truncation,
`shutil.which` extensionless-name behavior), and multiplexer notes.
Start at **`references/troubleshooting.md`**.

## Other agent harnesses

The procedure is harness-neutral; only the skill file is
agent-skills-standard. Copy the folder into any harness's skills dir
(Claude Code / Codex / Gemini / Copilot: `.claude/skills/`,
`.agents/skills/`, `~/.agents/skills/`; pi: `~/.pi/agent/skills/`).

## License

[MIT](./assets/adapter-pkg/LICENSE) — the adapter package and the skill
documentation.
