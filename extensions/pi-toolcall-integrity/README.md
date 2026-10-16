# pi-toolcall-integrity (extension)

Drops the fake empty-argument tool calls that pi persists when a provider
stream dies mid tool-call, and fails fast — with a readable message — when an
empty-arg call ever reaches execution.

Developed against `pi-coding-agent` 1.0.0. Re-verify after pi upgrades: the
`message_end` / `tool_call` event API is what this extension binds to.

## The bug (background)

When a provider stream ends without `finish_reason` (connection drop mid
response — happens on flaky pools), pi-ai keeps the in-flight `toolCall` block
in the persisted assistant message with `arguments: {}`. That call was never
executed, but the entry looks like a real empty-parameter call in session
logs. The durable fix lives in pi-ai itself; upstream status:
[earendil-works/pi#10435](https://github.com/earendil-works/pi/issues/10435),
patch in [`../../patches/pi-ai-truncated-toolcalls`](../../patches/pi-ai-truncated-toolcalls/).

What pi already does built-in: auto-retry re-sends the dropped request (up to
3× by default), and replay skips errored turns entirely. What is left: the log
contamination and a cryptic `Validation failed for tool "write"` on the
success-path variant. This extension covers both.

## The two hooks

1. **`message_end` cleanup** — when an assistant turn ends with `stopReason`
   `error` or `aborted`, tool-call blocks whose `arguments` is an empty object
   are removed from the message *before* it is persisted to the session log
   (extension replacements are applied in `agent-session` ahead of
   `appendMessage`). Text/thinking blocks are kept.
2. **`tool_call` guard** — when an empty-argument call of a tool that requires
   arguments (`write`, `edit`, `bash`, `powershell`, `read`, `grep`, `find`)
   survives to execution, it is blocked with:
   > Tool call "write" arrived with empty arguments — this usually means the
   > provider stream was cut off mid call … Re-issue the tool call with
   > complete arguments.
   The model then re-issues instead of hitting a raw schema-validation error.
   `ls` is not blocked: a zero-argument `ls` is valid. Custom/MCP tools are
   left to pi's built-in TypeBox validation (schemas unknown to this extension).

## Install

```sh
mkdir -p ~/.pi/agent/extensions
cp pi-toolcall-integrity.ts ~/.pi/agent/extensions/pi-toolcall-integrity.ts
# then start (or /reload) pi
```

Uninstall: delete the file, reload.

## Test

```sh
node test/smoke.mjs    # Node >= 22.18 (type stripping on); 13 assertions
```

## Limitations

- Catches only the *empty-object* argument signature. A truncated stream whose
  partial JSON was auto-completed into a non-empty object is indistinguishable
  from a real call at the extension layer; that case needs the upstream
  `argsComplete` fix.
- The `tool_call` block only helps when the empty call actually survives to
  execution (successful turn with `stopReason: "toolUse"`). On errored turns
  the agent loop never executes tool calls, so hook ① alone applies.

MIT.
