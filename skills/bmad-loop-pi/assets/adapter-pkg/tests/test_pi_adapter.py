"""No-LLM test suite for the bmad-loop pi adapter.

Runs against the INSTALLED package (the bmad-loop uv tool environment):

    uv tool run --from bmad-loop python <this-dir>/test_pi_adapter.py

stdlib-only (unittest), no pytest dependency. Versioned against the
bmad-loop 0.13.2 + pi 1.2.0 seam (see the package docstring and the
skill's references/seam-drift-audit.md): a bmad-loop release that moves a
seam will fail these tests, which is the point — re-audit, patch the
adapter, then re-baseline the expectations.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
FAKE_PI = HERE / "fake_pi.py"

from bmad_loop.adapters.base import SessionSpec
from bmad_loop.adapters.profile import CLIProfile, HookSpec
from bmad_loop.model import TokenUsage
from bmad_loop_adapter_pi.pi_adapter import PiAdapter, PiDevAdapter


def _profile() -> CLIProfile:
    return CLIProfile(
        name="pi",
        binary="pi",
        adapter="pi",
        skill_tree=".agents/skills",
        prompt_template="Do exactly this and stop: {prompt}",
        bypass_args=["--approve"],
        model_flag="--model",
        hooks=HookSpec("none", "", {}),
    )


def _policy() -> types.SimpleNamespace:
    return types.SimpleNamespace(
        limits=types.SimpleNamespace(
            dev_stall_grace_s=600,
            dev_stall_nudges=2,
            dev_contract_nudge=False,
        )
    )


def _adapter(run_dir: Path, task_extra: dict | None = None, **kw) -> PiAdapter:
    return PiAdapter(
        run_dir=run_dir,
        policy=_policy(),
        profile=_profile(),
        extra_args=(),
        usage_grace_s=0.0,
        stop_without_result_nudges=1,
        events_dir=None,
        **(task_extra or {}),
        **kw,
    )


def _spec(cwd: Path, task_id: str, env: dict | None = None) -> SessionSpec:
    return SessionSpec(
        task_id=task_id,
        role="dev",
        prompt="do the fake work",
        cwd=cwd,
        env=env or {},
        timeout_s=300,
    )


class RegistrationTest(unittest.TestCase):
    def test_kind_registered_and_buildable(self):
        from bmad_loop.adapters.registry import get_adapter_kind

        kind = get_adapter_kind("pi")
        self.assertFalse(kind.needs_mux, "pi transport is self-hosted; no multiplexer")
        builder = kind.load()
        import inspect

        self.assertIn("paths", inspect.signature(builder.dev.__init__).parameters)


class ResolveBinaryTest(unittest.TestCase):
    """`_resolve_pi_argv` must survive the managed-install bin layout
    (POSIX `pi` script + `pi.cmd` launcher) and plain POSIX installs.
    Fully hermetic: PATH is replaced, not extended, so the host's own pi
    install can never leak into the result."""

    def _resolve_with(self, bin_files: dict[str, bytes]):
        """Run resolution under a hermetic PATH; returns (prefix | None, tmpdir).
        None = the adapter refused (nothing launchable on PATH)."""
        tmp = tempfile.mkdtemp(prefix="bmadloop-pi-test-")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        for name, content in bin_files.items():
            (Path(tmp) / name).write_bytes(content)
        old = os.environ.get("PATH", "")
        os.environ["PATH"] = tmp
        self.addCleanup(lambda: os.environ.__setitem__("PATH", old))
        from bmad_loop_adapter_pi.pi_adapter import _resolve_pi_argv

        try:
            return _resolve_pi_argv(), Path(tmp)
        except FileNotFoundError:
            return None, Path(tmp)

    def test_plain_posix_binary(self):
        """Only the POSIX `pi` on PATH.

        POSIX: it is launchable, use it directly. Windows: an extensionless
        shell script is NOT launchable there (modern `shutil.which` doesn't
        even match it) — the adapter must refuse rather than spawn garbage.
        """
        prefix, tmp = self._resolve_with({"pi": b"#!/bin/sh\necho hi\n"})
        if os.name == "nt":
            self.assertIs(prefix, None)
        else:
            self.assertEqual(prefix, [str(tmp / "pi")])

    def test_managed_layout_resolves_launcher_pair(self):
        """POSIX `pi` script + `pi.cmd` + `pi-launcher.js` + a node.exe:
        must yield [node, pi-launcher.js] — never the POSIX script through
        CreateProcess, never cmd /c. On POSIX hosts the .cmd pair is ignored
        and the bare script is used directly."""
        prefix, tmp = self._resolve_with(
            {
                "pi": b"#!/bin/sh\necho hi\n",
                "pi.cmd": b"@echo off\nnode %~dp0pi-launcher.js %*\n",
                "pi-launcher.js": b"// launcher\n",
                "node.exe": b"\x00\x00",  # which() only needs the name to resolve
            }
        )
        if os.name == "nt":
            # Windows file APIs may return the on-disk case (node.EXE) even
            # though the name was requested lowercase — compare casefolded.
            self.assertEqual(
                [p.casefold() for p in prefix],
                [str(tmp / "node.exe").casefold(), str(tmp / "pi-launcher.js").casefold()],
                prefix,
            )
        else:
            self.assertEqual(prefix, [str(tmp / "pi")])

    def test_windows_degrades_to_cmd_without_node(self):
        """pi.cmd present but no node anywhere: the resolution must degrade
        to the .cmd itself (OS batch routing), not fail outright."""
        if os.name != "nt":
            self.skipTest("Windows-only .cmd fallback")
        prefix, tmp = self._resolve_with(
            {
                "pi.cmd": b"@echo off\nnode %~dp0pi-launcher.js %*\n",
                "pi-launcher.js": b"// launcher\n",
            }
        )
        self.assertIsNotNone(prefix, "the .cmd must be found by the bare pi lookup")
        self.assertIn("pi", Path(prefix[0]).name.lower())

    def test_missing_binary_refuses(self):
        prefix, _ = self._resolve_with({})
        self.assertIs(prefix, None, "no launchable pi on PATH must raise FileNotFoundError")


class UsageParserTest(unittest.TestCase):
    """`_sum_usage_file` maps pi's session-JSONL usage records onto
    bmad-loop's TokenUsage. Deterministic fixture, no process involved."""

    def test_sums_all_three_record_kinds(self):
        tmp = tempfile.mkdtemp(prefix="bmadloop-pi-usage-")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        path = Path(tmp) / "s.jsonl"
        rows = [
            {"type": "session", "version": 3, "id": "x"},
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "usage": {"input": 1000, "output": 10, "cacheRead": 500, "cacheWrite": 0},
                },
            },
            {
                "type": "message",
                "message": {"role": "user", "content": "no usage on user rows"},
            },
            {
                "type": "usage",
                "kind": "cache_warm",
                "usage": {"input": 5, "output": 1, "cacheRead": 250, "cacheWrite": 50},
            },
            {"type": "compaction", "usage": {"input": 1, "output": 2, "cacheRead": 3, "cacheWrite": 4}},
            {"not-json": True},  # malformed line must be skipped, not fatal
        ]
        path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        got = PiAdapter._sum_usage_file(path)
        self.assertIsInstance(got, TokenUsage)
        self.assertEqual(got.input_tokens, 1006)
        self.assertEqual(got.output_tokens, 13)
        self.assertEqual(got.cache_read_tokens, 753)
        self.assertEqual(got.cache_creation_tokens, 54)

    def test_missing_file_is_none(self):
        self.assertIsNone(PiAdapter._sum_usage_file(Path(tempfile.gettempdir()) / "nope-pi.jsonl"))


class LifecycleTest(unittest.TestCase):
    """Full adapter lifecycle against `fake_pi.py` (no LLM, no network)."""

    def _adapter_with_fake(self, run_dir: Path, **dev_kw):
        adapter = _adapter(run_dir, **dev_kw)
        # Inject the fake binary: the adapter's own resolution is covered by
        # ResolveBinaryTest; here we pin the spawn target directly.
        adapter._binary_argv = [sys.executable, str(FAKE_PI)]
        return adapter

    def test_plain_no_result_is_stalled(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            cwd = run_dir / "cwd"
            cwd.mkdir()
            adapter = self._adapter_with_fake(run_dir)
            result = adapter.run(_spec(cwd, "t1"))
            self.assertEqual(result.status, "stalled", "no result.json -> fallback verdict")
            self.assertTrue(result.stop_seen)
            self.assertIsNotNone(result.transcript_path)
            self.assertTrue(Path(result.transcript_path).exists())
            usage = adapter.read_usage(result)
            self.assertIsNotNone(usage)
            self.assertEqual(usage.cache_read_tokens, 750)  # 500 + 250 fixture

    def test_plain_result_json_completes(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            cwd = run_dir / "cwd"
            cwd.mkdir()
            adapter = self._adapter_with_fake(run_dir)
            result_path = run_dir / "tasks" / "t2" / "result.json"
            spec = _spec(cwd, "t2", env={"FAKE_PI_RESULT": str(result_path)})
            result = adapter.run(spec)
            self.assertTrue(result_path.exists(), "fake pi must write the result file")
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.result_json, {"status": "done", "detail": "fake dev result"})

    def test_nonzero_exit_crashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            cwd = run_dir / "cwd"
            cwd.mkdir()
            adapter = self._adapter_with_fake(run_dir)
            result = adapter.run(_spec(cwd, "t3", env={"FAKE_PI_RC": "3"}))
            self.assertEqual(result.status, "crashed")

    def test_hard_stop_aborts(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            cwd = run_dir / "cwd"
            cwd.mkdir()
            adapter = self._adapter_with_fake(run_dir)
            (run_dir / "stop-request.json").write_text(json.dumps({"mode": "hard"}), encoding="utf-8")
            handle = adapter.start_session(_spec(cwd, "t4"))
            result = adapter.wait_for_completion(handle, _spec(cwd, "t4"))
            self.assertEqual(result.status, "aborted")


class DevSynthesisTest(unittest.TestCase):
    """The dev variant must fold the on-disk story spec into a completed
    result via bmad-loop's _DevSynthesisMixin. Versioned against the
    0.13.2 synthesis contract (see module docstring)."""

    def test_done_spec_synthesizes_completed(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            cwd = run_dir / "cwd"
            cwd.mkdir()
            artifacts = run_dir / "artifacts"
            artifacts.mkdir()
            spec_file = artifacts / "spec-fake-story.md"

            adapter = PiDevAdapter(
                run_dir=run_dir,
                policy=_policy(),
                profile=_profile(),
                extra_args=(),
                usage_grace_s=0.0,
                stop_without_result_nudges=1,
                events_dir=None,
                paths=types.SimpleNamespace(
                    implementation_artifacts=artifacts,
                    artifact_at=lambda base, _cwd: artifacts,
                ),
            )
            adapter._binary_argv = [sys.executable, str(FAKE_PI)]
            result = adapter.run(_spec(cwd, "d1", env={"FAKE_PI_SPEC": str(spec_file)}))
            self.assertTrue(spec_file.exists(), "fake pi must write the terminal spec")
            self.assertEqual(result.status, "completed", "terminal spec must synthesize a completed verdict")


if __name__ == "__main__":
    unittest.main(verbosity=2)
