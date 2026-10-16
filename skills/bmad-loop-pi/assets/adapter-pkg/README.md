# bmad-loop-adapter-pi

Out-of-tree bmad-loop adapter that drives the **pi coding agent**
(`@earendil-works/pi-coding-agent`) as a coding CLI for bmad-loop's
dev/review/retro/sweep sessions.

bmad-loop 0.13.x has no built-in `pi` profile (`bmad-loop init --cli pi`
fails with `unknown CLI profile`), but its documented out-of-tree path —
a co-installed package registering an adapter kind via the
`bmad_loop.adapters` entry point plus a project profile in
`.bmad-loop/profiles/` — is exactly what this package is.

## Transport

pi has no lifecycle-hook settings file bmad-loop can write (its extension
system is JS modules, not declarative settings), so the adapter is
self-hosted like the opencode-http family:

| Axis        | Value             | Meaning                                             |
|-------------|-------------------|-----------------------------------------------------|
| injection   | `launch-flag`     | prompt goes on the command line (`pi -p …`)         |
| observation | `transcript-poll` | completion = process exit + on-disk session file    |
| state       | `local-jsonl`     | token usage summed from pi's session JSONL          |

One `pi -p` process per bmad-loop session; transcripts land under
`.bmad-loop/runs/<run>/pi-sessions/`, logs under `…/logs/`.

## Known consequences (vs the pane+hook families)

- **No stall wake-nudges.** A turn that ends without its result artifact
  degrades to `stalled` and the run pauses per policy, instead of being
  nudged.
- **No attach.** The TUI shows logs, not a live pane.
- **`--approve` is load-bearing:** pi's first-run workspace-trust dialog
  cannot be answered by a spawned process; the profile passes it per run.

## Install

The package normally ships inside the `bmad-loop-pi` skill's assets and is
co-installed from there (`uv tool install bmad-loop --with <skill>/assets/adapter-pkg`).
Co-install from any stable path, e.g. a checkout:

```bash
uv tool install "bmad-loop[tui] @ git+https://github.com/bmad-code-org/bmad-loop.git" \
  --with "/path/to/bmad-loop-adapter-pi"
```

Then, in the project:

```powershell
bmad-loop init --project . --cli pi     # hookless: registers skills only
# .bmad-loop/profiles/pi.toml ships with the setup (copy it if new)
# .bmad-loop/policy.toml:
#   [adapter]
#   name = "pi"
bmad-loop validate
```

## Windows / POSIX binary resolution

Where the pi launcher is a `.cmd`/`.ps1` shim next to a POSIX `pi` shell
script (the pi managed-install layout), `shutil.which("pi")` returns the
POSIX script, which `CreateProcess` cannot execute. The adapter resolves
`pi.cmd` → `node pi-launcher.js` and passes arguments as a true argv list
(`CreateProcess` quoting), never through `cmd /c`. On POSIX hosts the bare
`pi` executable is used directly.

## Testing

The suite is stdlib-only (unittest, no pytest dependency) and runs against
the installed package — same environment bmad-loop itself loads:

```bash
uv tool run --from bmad-loop python tests/test_pi_adapter.py
```

It covers: entry-point registration, binary resolution (POSIX + Windows
launcher layout), the session-file usage parser, and the full lifecycle
(spawn → wait → result read-back → kill → evict) against `tests/fake_pi.py`,
a deterministic no-LLM pi emulator. The dev-mixin synthesis test is
versioned against the bmad-loop 0.13.2 contract (see CHANGELOG) — it is a
deliberate canary for seam drift, not a fixed oracle.

For live end-to-end wiring (real pi, one cheap turn), see the skill's
`assets/smoke.py`.

## License

MIT — see [LICENSE](./LICENSE).
