# Changelog

All notable changes to the `bmad-loop-adapter-pi` package.

The package is a **reference implementation, seam-verified against one
bmad-loop release and one pi release** — the version line of each entry is
the contract. When bmad-loop or pi moves, patch this package in place and
add an entry; do not treat older entries as still-valid pins.

## 0.1.0 — 2026-12

Seam-verified: bmad-loop 0.13.2 + pi 1.2.0.

- `pi` adapter kind registered via the `bmad_loop.adapters` entry point
  (`needs_mux=False`, self-hosted print-mode transport).
- `PiAdapter`: one `pi -p` process per session; completion = process exit +
  session-JSONL discovery; token usage summed from pi's session file
  (assistant-message `usage`, `usage` entries, compaction/branch-summary
  `usage`) into bmad-loop's `TokenUsage`.
- `PiDevAdapter` composes bmad-loop's `_DevSynthesisMixin` so dev/review
  sessions synthesize the result from the story spec the bmad-build-auto
  skill leaves on disk (the skill writes no result.json).
- Windows binary resolution: `pi.cmd` → `node pi-launcher.js` argv list
  (CreateProcess quoting; never `cmd /c`). Modern Python `shutil.which`
  does not match extensionless names on Windows, so node is looked up as
  `node.exe` first; a POSIX-only layout correctly refuses to spawn.
- Log-file handles are released immediately after spawn (the child holds
  its own kernel handles) so a long run does not accumulate BufferedWriter
  handles.
- No stall wake-nudges, no TUI attach (documented design, not a gap).
- Tests: stdlib-unittest suite `tests/test_pi_adapter.py` (registration,
  binary resolution incl. the Windows `which()` extension pitfall, usage
  parser, plain + crash + hard-stop lifecycles, dev-mixin synthesis)
  plus `tests/fake_pi.py` — a deterministic no-LLM pi emulator. Live LLM
  wiring is covered separately by the skill's `smoke.py`.
