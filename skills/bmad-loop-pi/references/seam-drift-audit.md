# Seam-drift audit (bmad-loop × pi adapter)

Run this **after any bmad-loop or pi version bump**, and whenever a
`bmad-loop adapters` / `validate` / run-start error mentions the `pi`
profile. The bundled adapter is a reference implementation seam-verified
on **bmad-loop 0.13.2 + pi 1.2.0 (2026-12)**; every item below names the
exact contract to re-verify against the *installed* bmad-loop, and what
to patch where if it moved.

Locate the installed source first:

```sh
uv tool run --from bmad-loop python -c "import bmad_loop, pathlib; print(pathlib.Path(bmad_loop.__file__).parent)"
```

(`uv tool run --from <tool> python …` — without `--from` the bare
tool-name form is eaten by bmad-loop's own argv parser.)

## The seven seams

1. **Registry seam — `adapters/registry.py`.**
   `register_adapter(name, needs_mux, load)` signature and
   `AdapterBuilder` fields (`plain`, `dev`, `construct_error`).
   If changed → patch `assets/adapter-pkg/bmad_loop_adapter_pi/__init__.py`.

2. **Adapter contract — `adapters/base.py`.**
   Capability-axis values still legal (`launch-flag`, `transcript-poll`,
   `local-jsonl`); `SessionSpec` fields the adapter reads
   (task_id/role/prompt/cwd/env/model/timeout_s/token_budget*/effort/expected_spec);
   `SessionHandle`/`SessionResult` constructor kwargs the adapter passes
   (extra dataclass fields are harmless; missing/renamed ones break
   construction). If changed → patch `pi_adapter.py` accordingly.

3. **Build kwargs — `runsetup.py` `make_adapters`.**
   The `common` kwarg set handed to `cls(**build_kwargs)`
   (run_dir, policy, profile, extra_args, usage_grace_s,
   stop_without_result_nudges, events_dir, mux when needs_mux, paths for
   the synthesizing variant) and the synthesizes discriminator
   (`policy.dev.skill`). The adapter's `__init__` must accept exactly
   what's handed — extra `**_ignored` is safe; a missing parameter name
   aborts the run with "adapter kind 'pi' rejected this run's adapter
   keywords".

4. **Dev-mixin host contract — `adapters/generic.py` `_DevSynthesisMixin`.**
   What it now requires of hosts: `_configure_dev_knobs` and which
   `policy.limits.*` names it reads, `_probe_alive`, `_evict_task_state`,
   attribute needs (`paths`, `policy`), and `_artifact_dirs`' expected
   return shape (one Path, not a list). Patch `PiDevAdapter`.

5. **Profile schema — `adapters/profile.py`.**
   `CLIProfile` required fields and `HOOK_DIALECTS`. Hookless must still
   be `dialect = "none"`. Unknown top-level keys are ignored, so
   `assets/pi-profile.toml` is forward-tolerant — patch it ONLY if new
   REQUIRED fields appear.

6. **Usage model — `model.py`.**
   `TokenUsage` field names and `weighted_total` semantics. The
   session-file parser maps pi's `input/output/cacheRead/cacheWrite` onto
   it; a rename shows up as a `read_usage` type error or budget-guard
   inactivity.

7. **pi side — `pi --help` + session-file layout.**
   The print-mode flags the argv builds (`-p`, `--approve`,
   `--session-dir`, `--session-id`, `--model`). Pi upgrades may rename
   them; re-derive from `--help`. Also re-confirm the session-file
   layout (`<session-dir>/<ts>_<id>.jsonl`, usage fields on assistant
   messages / usage entries / compaction) with the smoke.

## After patching

1. Re-run the SKILL.md §2 install (rebuilds the wheel from the patched
   assets — use `uv tool install --reinstall …` if the package is judged
   unchanged; verify the installed `pi_adapter.py` actually contains your
   edit before trusting the run).
2. Run the no-LLM unit suite (SKILL.md § "No-LLM unit suite"). The
   dev-synthesis test failing = seam drift confirmed — patch, don't
   re-baseline.
3. Re-run `bmad-loop validate`, then the smoke — and **re-derive the
   expected smoke output from this version's behavior** instead of
   matching the 0.13.2 text.
4. Keep the patched assets as the source of truth (the uv environment
   builds from them). If the operator keeps a separate checkout of the
   package, sync it manually. Update the package's `CHANGELOG.md` and
   the "seam-verified on …" headers with the new version pair.

## Source-file → seam map (what to edit where)

| Drift observed in | Edit |
|---|---|
| registration / builder shape | `bmad_loop_adapter_pi/__init__.py` |
| SessionSpec/Handle/Result fields, axes, hard-stop | `bmad_loop_adapter_pi/pi_adapter.py` (`PiAdapter`) |
| new build kwargs / synthesizes discriminator | `PiAdapter.__init__` (accept + store, or use) |
| dev-mixin requirements (`_configure_dev_knobs`, `_probe_alive`, eviction, artifact dirs) | `PiDevAdapter` |
| profile fields / dialects | `assets/pi-profile.toml` |
| TokenUsage shape | `_sum_usage_file` in `pi_adapter.py` |
| pi CLI flags / session layout | argv building + `_session_file` + fake_pi in tests |
