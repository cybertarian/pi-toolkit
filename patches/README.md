# patches/

Upstream pi source diffs that are not (yet) part of a pi release. Each
subdirectory is one fix: the `.patch` file(s), a `README.md` with the base
commit, apply instructions, and the linked upstream issue, and the test
evidence.

Patches are applied to a pi checkout, not installed like the other kinds.
When a patch lands upstream, the directory is marked `superseded` (link the
release) but kept for reference.

| Patch | Targets | Status |
|---|---|---|
| [pi-ai-truncated-toolcalls](pi-ai-truncated-toolcalls/) | `packages/ai` (openai-completions streaming) | pending upstream — [#10435](https://github.com/earendil-works/pi/issues/10435) |
