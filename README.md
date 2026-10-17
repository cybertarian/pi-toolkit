# 🧰 Pi Toolkit

[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)

Independently installable add-ons for the [Pi Coding Agent](https://github.com/earendil-works/pi):
in-process extensions, agent skills, and upstream source patches.

Install only what you need. Each component lives in its own directory with its own
`README.md` — the layout and conventions are at the [bottom](#️-repository-structure--conventions).

## 🚀 Quick start

Install the **pi-toolcall-integrity** extension (keeps truncated tool calls out of your session logs):

```bash
mkdir -p ~/.pi/agent/extensions
cp extensions/pi-toolcall-integrity/pi-toolcall-integrity.ts ~/.pi/agent/extensions/pi-toolcall-integrity.ts
# start pi, or run /reload
```

Install the **bmad-loop-pi** skill (drive pi with bmad-loop):

```bash
cp -r skills/bmad-loop-pi ~/.pi/agent/skills/
```

Apply the **pi-ai truncated-tool-call fix** to a local pi checkout:

```bash
git clone https://github.com/cybertarian/pi-toolkit
git -C <pi-checkout> am -3 pi-toolkit/patches/pi-ai-truncated-toolcalls/*.patch
```

> [!IMPORTANT]
> Pi extensions run inside Pi with your full user permissions.
> Review any third-party extension before installing it.

## 📦 Choose a component

### Extensions

In-process TypeScript loaded from `~/.pi/agent/extensions/`.

| Component | Use it for | Install |
| --- | --- | --- |
| [`pi-toolcall-integrity`](./extensions/pi-toolcall-integrity) | Drop the fake empty-argument tool calls pi persists when a provider stream dies mid tool-call, and fail fast with a readable "re-issue" message instead of a cryptic schema error when one slips through. | copy `pi-toolcall-integrity.ts` to `~/.pi/agent/extensions/` |
| [`pi-agnes-multikey-bridge`](./extensions/pi-agnes-multikey-bridge) | Spread pi-agnes-tools' image/video generation across a pi-multikey pool: round-robins the env key per call + transparently retries 401/403/429 on the next pool key — pi-agnes-tools untouched. | copy `pi-agnes-multikey-bridge.ts` to `~/.pi/agent/extensions/` |

### Skills

Agent skills loaded from `~/.pi/agent/skills/`.

| Component | Use it for | Install |
| --- | --- | --- |
| [`bmad-loop-pi`](./skills/bmad-loop-pi) | Set up [bmad-loop](https://github.com/bmad-code-org/bmad-loop) to drive pi as its coding CLI: out-of-tree `pi` adapter, profile, validation, and a live wiring smoke. | copy the folder to `~/.pi/agent/skills/` |

### Patches

Upstream pi source diffs — applied to a pi checkout, not installed.

| Component | Use it for | Apply |
| --- | --- | --- |
| [`pi-ai-truncated-toolcalls`](./patches/pi-ai-truncated-toolcalls) | The durable fix for the fake empty-argument tool calls: track `argsComplete` per streaming tool-call block and drop incomplete calls on stream error. | `git am -3` into a pi checkout · [upstream status](https://github.com/earendil-works/pi/issues/10435) |

More kinds are on the roadmap — `plugins/` (npm-installable packages) and `mcp/`
(MCP servers) are reserved top-level directories; a new kind is added only when
its first component lands. Components are source-only for now (no npm
publishing); install from this repository as shown above.

## 🗂️ Repository structure & conventions

```text
extensions/   In-process TS extensions       ->  ~/.pi/agent/extensions/
skills/       Agent skills (SKILL.md + …)    ->  ~/.pi/agent/skills/
plugins/      npm-installable packages       ->  ~/.pi/agent/npm/   (future)
mcp/          MCP servers / adapters                          (future)
patches/      Upstream pi source diffs       ->  applied, not installed
```

Conventions:

- **One directory per component**, kebab-case with the `pi-` prefix, matching pi
  ecosystem package naming (`pi-goal`, `pi-statusline`, …). Entry files stay
  conventional to their kind (a single `.ts` for extensions, `SKILL.md` for
  skills).
- Every component ships its own `README.md` and, where behavior is non-trivial,
  a runnable test under `test/`. Components never depend on each other —
  share code through a package instead.
- Record the pi version a component was developed against in its README
  (`pi >= X.Y.Z`); re-verify after pi upgrades, since extensions and plugins
  couple to pi's event/tool API.
- Patches are named for the pi subsystem they touch (`pi-ai-…`) and carry a
  `README.md` stating the base commit, apply instructions, and the linked
  upstream issue.
- A new top-level kind appears only when its first component lands. This is a
  solo-maintained toolkit — there is no external contribution flow; upstream
  fixes go to the pi repository itself.

## 📄 License

MIT. See [`LICENSE`](./LICENSE).
