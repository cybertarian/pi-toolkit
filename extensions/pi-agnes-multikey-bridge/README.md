# pi-agnes-multikey-bridge (extension)

Spreads [pi-agnes-tools](https://github.com/DraconDev/pi-agnes-tools) image/video
generation across every key of a
[pi-multikey](https://github.com/...) pool — without modifying pi-agnes-tools
or any pi settings.

Developed against `pi-coding-agent` 1.1.0, `pi-agnes-tools` 0.3.7,
`pi-multikey` 1.19.0. Re-verify after upgrades: this extension binds to the
`tool_execution_start` event and to pi-agnes-tools' "env var first" key
resolution; either changing is enough to make it silently ineffective.

## Problem

`pi-agnes-tools` resolves its API key as `AGNES_API_KEY` env → /login-stored
key in `auth.json` (a single key). Generation calls therefore use one pool
account and fail the moment that account is rate-limited. `pi-multikey` keeps
4 keys in `~/.pi/agent/multikey.json` but nothing in the generation path
consults it.

## How it works

Two mechanisms, one auto-discovered extension file:

1. **Round-robin via the env var.** On pi's `tool_execution_start` event
   (emitted before the tool's `execute()` runs), the bridge writes
   `AGNES_API_KEY` / `AGNES_CN_API_KEY` to the next key of the matching
   pool (matched by baseUrl host). pi-agnes-tools reads the env var first,
   so each generation call — concurrent calls included — lands on a
   different pool account.
   - A pool without matching host ⇒ no write, upstream fallback untouched.
   - Env var already set at process start ⇒ never clobbered
     (deterministic single-key behavior preserved).
2. **Transparent 401/403/429 rotation.** The bridge wraps
   `globalThis.fetch` (same process). Only in-scope requests are touched:
   pool hosts + `/v1/images/*`, `/v1/videos*`, `/agnesapi` status paths.
   The original request is always sent first, unchanged; on a rotatable
   failure the remaining pool keys are tried in order (retries hit the
   underlying fetch directly — no recursion). 400/timeout errors and
   out-of-scope URLs (chat pipelines, other hosts) pass through, so
   pi-multikey's own rotation and pi-ai's stream handling are unaffected.

pi-agnes-tools stays fully enabled (tools, providers, skill, and its
`before_provider_request` sanitizer all keep running). This extension
registers no tools, so there is no cross-extension name conflict.

## Install

Requires the `pi-agnes-tools` and `pi-multikey` packages installed in pi.

```bash
mkdir -p ~/.pi/agent/extensions
cp extensions/pi-agnes-multikey-bridge/pi-agnes-multikey-bridge.ts ~/.pi/agent/extensions/
# start pi, or run /reload
```

Uninstall: delete the file, /reload.

## Verify

```bash
node test/smoke.mjs   # Node >= 22.18; zero-quota hermetic test
```

Live observation (optional): start pi with `PI_AGNES_BRIDGE_DEBUG=1` —
stderr prints `[pi-agnes-multikey-bridge]` lines for every env swap and
fetch rotation. A `PI_AGNES_BRIDGE_MULTIKEY_CONFIG` env var redirects the
pool lookup to another multikey.json (used by the smoke test; also handy
for debugging).

## Boundaries

- Pool edits via /multikey apply immediately (config is re-read per call).
- Only 401/403/429 trigger rotation; generation-side errors propagate.
- If pi-agnes-tools ever ships native multikey support, delete this file.
