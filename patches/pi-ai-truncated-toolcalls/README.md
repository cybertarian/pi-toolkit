# patch: pi-ai — drop truncated tool-call blocks on stream error

**Targets** `packages/ai/src/api/openai-completions.ts` (and a test file).

## What it changes

When the provider stream dies mid tool-call (`Stream ended without
finish_reason`), the catch block currently strips the scratch fields
(`partialArgs`, `customInput`) but keeps the truncated `toolCall` block, so
the persisted message carries a fake `write`/`edit` call with
`arguments: {}`.

The patch adds an `argsComplete` flag per streaming tool-call block:

- set in the delta loop — true when the accumulated raw argument JSON
  strictly parses (`parseJsonWithRepair`), false otherwise; for grammar
  (custom-input) tools, from `jsonBuffer.closed`.
- on the **error path**: tool-call blocks without `argsComplete` are spliced
  out of the message before it is emitted/persisted. Text and thinking blocks
  are kept, and calls whose arguments *did* fully stream before the drop are
  kept too.
- on the **success path**: the flag is stripped with the other scratch
  fields (it must not leak into persisted messages).

Behavior consequence: after a dropped stream, the persisted errored message
contains no bogus empty-argument tool call; the agent re-issues on the next
turn (and pi's auto-retry already re-sends the whole request, so in practice
the user sees a clean retry).

## Apply

```sh
# in a pi checkout (main @ 8369268 / pi-ai 1.0.1; the two touched files are
# unchanged in the v1.0.4 cycle, verified 2026-10-06)
git am -3 0001-*.patch 0002-*.patch     # or: git apply --3way *.patch
```

Then, from `packages/ai`:

```sh
node <repo>/node_modules/vitest/dist/cli.js --run test/openai-completions-truncated-toolcalls.test.ts
node <repo>/node_modules/vitest/dist/cli.js --run openai-completions   # 116 tests
npx tsc --noEmit
```

All green at development time: 4 new regression tests + 116 existing
openai-completions tests + `npm run check`.

## Upstream status

- Issue: [earendil-works/pi#10435](https://github.com/earendil-works/pi/issues/10435)
  (reopened by a maintainer 2026-10-05; waiting for `lgtm` per the repo's
  contribution gate).
- Branch: [`cybertarian/pi` @ `fix/openai-completions-truncated-toolcalls`](https://github.com/cybertarian/pi/tree/fix/openai-completions-truncated-toolcalls)
  (2 commits; rebase onto current main before opening the PR).
