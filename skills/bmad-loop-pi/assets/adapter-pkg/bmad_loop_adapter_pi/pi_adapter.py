"""bmad-loop adapter kind ``pi`` — drive the pi coding agent in print mode.

pi (``@earendil-works/pi-coding-agent``) has no lifecycle-hook settings file
that bmad-loop's declarative hook dialects can write (its extension system is
JS modules, not settings JSON), so it cannot ride the built-in ``generic``
pane+hook transport. Instead this adapter is self-hosted, like the
opencode-http family:

- injection  = ``launch-flag``   — the prompt goes on the command line
  (``pi -p <prompt>``), one process per bmad-loop session.
- observation = ``transcript-poll`` — completion is the process exit; the
  turn is proven by the on-disk session file and the skill's spec/result
  artifacts (the dev variant composes ``_DevSynthesisMixin``).
- state      = ``local-jsonl``  — pi's session file carries per-message
  ``usage`` (``input/output/cacheRead/cacheWrite``), summed for the
  session-budget guard.

What this means operationally:

- No stall wake-nudges: a session is one ``pi -p`` invocation that runs to
  its natural end (or the session timeout / token budget). A turn that ends
  without writing its result artifact degrades to ``stalled`` and the engine
  pauses per policy, instead of being nudged.
- No attach: ``bmad-loop tui`` shows the logs, not a live pane.
- ``--approve`` (profile ``bypass_args``) trusts project-local files per run,
  which also covers fresh worktree isolation dirs; pi's first-run trust
  dialogs cannot be answered by spawned sessions, so this flag is load-bearing.

VERSIONING: reference implementation, seam-verified against bmad-loop 0.13.2
+ pi 1.2.0 (2026-12). The bmad-loop upgrade path is the skill's
references/seam-drift-audit.md (seven seams) — patch this module in place
when a seam moves, then rebuild the uv tool environment and re-run the
tests with the expectations re-derived.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from bmad_loop import runs
from bmad_loop.adapters.base import (
    CodingCLIAdapter,
    SessionHandle,
    SessionResult,
    SessionSpec,
    TokenUsage,
)
from bmad_loop.adapters.generic import _DevSynthesisMixin
from bmad_loop.journal import TASK_CYCLE_ARTIFACTS

# Poll cadence for the wait loop; keeps a torn run resumable within one tick.
POLL_S = 5.0

# Settle window after process exit before reading the session file: pi writes
# entries incrementally, the last assistant message lands before exit, but a
# brief flush tail is cheap to wait out.
_FLUSH_TAIL_S = 1.0


def _resolve_pi_argv() -> list[str]:
    """Locate a launchable pi executable.

    ``shutil.which("pi")`` in a pi managed-install layout returns the
    POSIX ``pi`` shell script (``#!/bin/sh``) sitting next to the Windows
    launcher, which CreateProcess cannot execute. The Windows launcher is
    ``pi.cmd`` (``node %~dp0pi-launcher.js``); we resolve the node +
    launcher pair directly so Popen receives an argv list
    (proper per-argument quoting via CreateProcess) instead of routing the
    prompt text through ``cmd /c`` where it would meet batch-file quoting
    hazards.
    """
    if os.name == "nt":
        cmd = shutil.which("pi.cmd") or shutil.which("pi.exe")
        if cmd:
            # node may be node.exe (npm/managed layouts) or a bare `node`
            # (POSIX-style installs that reach Windows); on modern Python
            # `shutil.which` does not match extensionless names on Windows,
            # so try the explicit .exe first.
            node = shutil.which("node.exe") or shutil.which("node")
            if node:
                launcher = Path(cmd).parent / "pi-launcher.js"
                if launcher.is_file():
                    return [node, str(launcher)]
            # No node / no launcher next to the .cmd: fall through to the
            # bare `pi` lookup (which PATHEXT-matches the .cmd itself; the OS
            # then routes it through its batch wrapper — acceptable degraded
            # path, never preferred).
    found = shutil.which("pi")
    if found:
        return [found]
    raise FileNotFoundError(
        "pi not found on PATH (looked for pi.cmd/pi.exe, then pi)"
    )


class _ProcessRecord:
    """One launched pi process and its transcript location."""

    def __init__(
        self,
        proc: subprocess.Popen,
        session_dir: Path,
        session_id: str,
        argv_tail: list[str],
    ) -> None:
        self.proc = proc
        self.session_dir = session_dir
        self.session_id = session_id
        # Everything after the pi binary (for diagnostics, not re-launch).
        self.argv_tail = argv_tail


class PiAdapter(CodingCLIAdapter):
    """Self-hosted print-mode adapter for the pi coding agent."""

    name = "pi"
    injection = "launch-flag"
    observation = "transcript-poll"
    state = "local-jsonl"

    def __init__(
        self,
        *,
        run_dir: Path,
        policy: Any,
        profile: Any,
        extra_args: tuple[str, ...] | None = None,
        usage_grace_s: float | None = None,
        stop_without_result_nudges: int | None = None,
        events_dir: Any = None,
        mux: Any = None,
        paths: Any = None,
        **_ignored: Any,
    ) -> None:
        # The engine attaches `journal` after construction; this adapter
        # writes no journal entries, so None is a fine resting value.
        self.journal = None
        self.run_dir = Path(run_dir)
        self.policy = policy
        self.profile = profile
        self.extra_args = tuple(extra_args or ())
        self.usage_grace_s = float(usage_grace_s or 0.0)
        self.stop_without_result_nudges = stop_without_result_nudges
        self.events_dir = events_dir
        self.mux = mux  # unused; needs_mux=False families never get one
        self.paths = paths
        self.tasks_dir = self.run_dir / "tasks"
        self._procs: dict[str, _ProcessRecord] = {}
        self._binary_argv: list[str] | None = None

    # ------------------------------------------------------------------ launch

    def _pi_argv_prefix(self) -> list[str]:
        if self._binary_argv is None:
            self._binary_argv = _resolve_pi_argv()
        return list(self._binary_argv)

    def start_session(self, spec: SessionSpec) -> SessionHandle:
        prompt = self.profile.render_prompt(spec.prompt)
        session_id = uuid.uuid4().hex
        session_dir = self.run_dir / "pi-sessions"
        session_dir.mkdir(parents=True, exist_ok=True)

        task_dir = self.tasks_dir / spec.task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        # Shared cycle artifacts reset on every relaunch (id reuse), per the
        # base contract: result.json / escalation.json may be leftovers of a
        # previous attempt and would masquerade as this session's result.
        for artifact in TASK_CYCLE_ARTIFACTS:
            try:
                (task_dir / artifact).unlink()
            except (FileNotFoundError, OSError):
                pass

        argv = [
            *self._pi_argv_prefix(),
            "-p",
            prompt,
            "--approve",
            "--session-dir",
            str(session_dir),
            "--session-id",
            session_id,
        ]
        if spec.model:
            argv += [self.profile.model_flag or "--model", spec.model]
        # A policy extra_args replaces the profile's bypass flags, same as the
        # built-in families.
        argv += list(self.extra_args) if self.extra_args else list(self.profile.bypass_args)

        logs_dir = self.run_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        out = open(logs_dir / f"{spec.task_id}.pi.out", "ab")
        err = open(logs_dir / f"{spec.task_id}.pi.err", "ab")
        launched_ns = time.time_ns()
        try:
            proc = subprocess.Popen(
                argv,
                cwd=str(spec.cwd),
                env=dict(spec.env),
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=err,
            )
        except OSError:
            out.close()
            err.close()
            raise
        # Release the parent-side file objects now that the child holds its
        # own kernel handles: the Popen object never touches the file
        # objects after spawn, and leaving them open would accumulate
        # BufferedWriters for the whole run (90 min x every session).
        out.close()
        err.close()
        self._procs[spec.task_id] = _ProcessRecord(proc, session_dir, session_id, argv[2:])
        return SessionHandle(
            task_id=spec.task_id,
            native_id=str(proc.pid),
            launched_ns=launched_ns,
            pinned_session_id=session_id,
        )

    # ------------------------------------------------------------------- wait

    def _hard_stop_requested(self) -> bool:
        """Mirror of ``_ResultFileMixin._hard_stop_requested`` for the plain
        family (this class does not mix in the result-file mixin)."""
        if runs.read_stop_request_mode(self.run_dir) == "hard":
            return True
        owner = runs.owner_run_dir()
        return (
            owner is not None
            and owner != self.run_dir
            and runs.read_stop_request_mode(owner) == "hard"
        )

    def _session_file(self, rec: _ProcessRecord) -> Path | None:
        if rec is None:
            return None
        try:
            for cand in rec.session_dir.glob(f"*_{rec.session_id}.jsonl"):
                return cand
        except (OSError, RuntimeError):
            pass
        return None

    @staticmethod
    def _sum_usage_file(path: Path) -> TokenUsage | None:
        """Sum one pi session file's usage records into a TokenUsage.

        pi contributes to its session totals from three record kinds:
        assistant-message ``usage`` (conversation), ``usage`` entries
        (model-attributed non-conversation work, e.g. cache warming) and
        optional ``usage`` on compaction / branch-summary entries. That is
        exactly the documented session accounting, so summing all three is
        pi's own total.
        """
        usage = TokenUsage()
        any_read = False
        try:
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(entry, dict):
                        continue
                    block = PiAdapter._entry_usage(entry)
                    if not isinstance(block, dict):
                        continue
                    usage.input_tokens += int(block.get("input", 0) or 0)
                    usage.output_tokens += int(block.get("output", 0) or 0)
                    usage.cache_read_tokens += int(block.get("cacheRead", 0) or 0)
                    usage.cache_creation_tokens += int(block.get("cacheWrite", 0) or 0)
                    any_read = True
        except (OSError, ValueError):
            usage.unread = (f"{path.name}: unreadable",)
            return None
        return usage if any_read else None

    def _finish(
        self,
        handle: SessionHandle,
        spec: SessionSpec,
        fallback: str,
        *,
        stop_seen: bool,
        budget_weighted: int | None = None,
    ) -> SessionResult:
        """Fold the on-disk evidence into the final result.

        Plain family: read the skill-written ``tasks/<task_id>/result.json``
        if present, else the fallback verdict. The dev variant overrides this
        with the ``_DevSynthesisMixin`` read-back (spec synthesis).
        """
        result_json: dict[str, Any] | None = None
        if fallback != "timeout" or stop_seen:
            path = self.tasks_dir / handle.task_id / "result.json"
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(doc, dict):
                    result_json = doc
            except (OSError, ValueError):
                result_json = None
        status = "completed" if result_json is not None else fallback
        rec = self._procs.get(handle.task_id)
        transcript = self._session_file(rec) if rec is not None else None
        return SessionResult(
            status=status,
            result_json=result_json,
            session_id=rec.session_id if rec is not None else None,
            transcript_path=str(transcript) if transcript is not None else None,
            budget_weighted=budget_weighted,
            stop_seen=stop_seen,
        )

    def wait_for_completion(
        self, handle: SessionHandle, spec: SessionSpec
    ) -> SessionResult:
        rec = self._procs.get(handle.task_id)
        if rec is None:  # a crash-resume or direct diagnostic call
            return SessionResult(status="crashed", session_id=spec.session_id)
        proc = rec.proc
        deadline = time.monotonic() + spec.timeout_s
        budget_weighted: int | None = None

        while True:
            # Hard-stop is polled on both sides of the blocking wait, like the
            # built-in families.
            if self._hard_stop_requested():
                self.kill(handle)
                return SessionResult(
                    status="aborted",
                    session_id=rec.session_id,
                    stop_seen=proc.poll() is not None,
                )
            try:
                proc.wait(timeout=POLL_S)
                break
            except subprocess.TimeoutExpired:
                passed = time.monotonic()
                if spec.token_budget and spec.token_budget_mode != "off":
                    usage = self._read_usage_file(rec)
                    if usage is not None:
                        weighted = usage.weighted_total(spec.cache_read_weight)
                        if weighted > spec.token_budget:
                            if spec.token_budget_mode == "enforce":
                                budget_weighted = weighted
                                self.kill(handle)
                                return self._finish(
                                    handle,
                                    spec,
                                    "over_budget",
                                    stop_seen=False,
                                    budget_weighted=weighted,
                                )
                            # warn mode: the built-in families journal an
                            # ATTENTION nudge; print mode has no nudge channel,
                            # so the trip is recorded but the session runs on.
                if passed >= deadline:
                    self.kill(handle)
                    return self._finish(
                        handle,
                        spec,
                        "timeout",
                        stop_seen=False,
                        budget_weighted=budget_weighted,
                    )

        rc = proc.returncode
        if rc is not None and rc != 0:
            # Flush tail: the failure already happened, no settle needed.
            return self._finish(handle, spec, "crashed", stop_seen=True)
        time.sleep(min(_FLUSH_TAIL_S, self.usage_grace_s or _FLUSH_TAIL_S))
        return self._finish(handle, spec, "stalled", stop_seen=True)

    # ------------------------------------------------------------------ usage

    @staticmethod
    def _entry_usage(entry: dict[str, Any]) -> dict[str, Any] | None:
        etype = entry.get("type")
        if etype == "usage":
            return entry.get("usage")
        if etype in ("compaction", "branch_summary"):
            return entry.get("usage")
        if etype == "message":
            message = entry.get("message") or {}
            if isinstance(message, dict) and message.get("role") == "assistant":
                return message.get("usage")
        return None

    def _read_usage_file(self, rec: _ProcessRecord) -> TokenUsage | None:
        path = self._session_file(rec)
        if path is None:
            return None
        return self._sum_usage_file(path)

    def read_usage(self, result: SessionResult) -> TokenUsage | None:
        if not result.transcript_path:
            return None
        return self._sum_usage_file(Path(result.transcript_path))

    # ------------------------------------------------------------------- kill

    def kill(self, handle: SessionHandle) -> None:
        rec = self._procs.get(handle.task_id)
        if rec is None:
            return
        proc = rec.proc
        if proc.poll() is not None:
            return
        if os.name == "nt":
            # pi spawns tool subprocesses (bash, etc.): kill the whole tree,
            # not just the node parent.
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                capture_output=True,
                check=False,
            )
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass

    # ------------------------------------------------------------- interactive

    def interactive_argv(self, spec: SessionSpec) -> list[str]:
        """Resume the session's pi transcript interactively, seeded with the
        escalation prompt (used by ``bmad-loop resolve`` escalation sessions).
        """
        rec = self._procs.get(spec.task_id)
        argv = [*self._pi_argv_prefix(), "--approve"]
        if rec is not None:
            argv += ["--session-dir", str(rec.session_dir), "--session-id", rec.session_id]
        if spec.model:
            argv += [self.profile.model_flag or "--model", spec.model]
        argv.append(self.profile.render_prompt(spec.prompt))
        return argv

    # Overridden by PiDevAdapter: the dev variant's read-back goes through the
    # mixin's synthesis path instead.
    def _session_vanished(self, task_id: str) -> bool:  # pragma: no cover - seam
        return False


class PiDevAdapter(_DevSynthesisMixin, PiAdapter):
    """Dev/review variant: synthesizes the result from the story spec the
    bmad-build-auto skill leaves on disk (the skill writes no result.json).

    MRO: ``_DevSynthesisMixin`` (run(), _final(), _result_json synthesis, the
    five per-task stores) over ``PiAdapter`` (the transport).
    """

    def __init__(self, *args: Any, paths: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.paths = paths
        self._configure_dev_knobs()

    def _finish(
        self,
        handle: SessionHandle,
        spec: SessionSpec,
        fallback: str,
        *,
        stop_seen: bool,
        budget_weighted: int | None = None,
    ) -> SessionResult:
        """Dev read-back: the mixin's ``_final`` (synthesis + proof-of-work
        gate) instead of the plain result.json read.
        """
        rec = self._procs.get(handle.task_id)
        transcript_path = self._session_file(rec)
        return self._final(
            handle,
            spec,
            fallback,
            handle.pinned_session_id,
            str(transcript_path) if transcript_path is not None else None,
            accept_result=True,
            budget_weighted=budget_weighted,
            stop_seen=stop_seen,
        )

    def _probe_alive(self, handle: SessionHandle) -> bool | None:
        rec = self._procs.get(handle.task_id)
        if rec is None or rec.proc is None:
            return None
        return rec.proc.poll() is None

    def _evict_task_state(self, task_id: str) -> None:
        super()._evict_task_state(task_id)
        self._procs.pop(task_id, None)
