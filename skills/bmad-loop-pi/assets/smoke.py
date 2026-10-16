"""Adapter wiring smoke test for the bmad-loop `pi` adapter (skill asset).

Usage:
    <bmad-loop uv-env python> smoke.py <project-root>

Runs ONE trivial pi session through PiDevAdapter (the dev variant bmad-loop
builds for dev/review roles). No story is involved.

NOTE ON EXPECTED OUTPUT: the baseline below was derived on bmad-loop 0.13.2
+ pi 1.2.0. This script is a drift canary, not a fixed oracle: after a
bmad-loop or pi version bump, re-derive expectations per the skill's
references/seam-drift-audit.md instead of matching the old text. The exit
code only asserts the transport did its job (a non-crashed verdict + a
non-empty hello.txt).

Expected at the 0.13.2 baseline: `stalled` with stop_seen=True (no story
spec existed to synthesize a result from), a nonzero TokenUsage, and
`hello.txt: OK`. A `crashed` verdict means pi itself failed — read
<project>/tmp/bmad-loop-pi-smoke/run/logs/smoke-1.pi.err.
"""

import importlib.metadata
import os
import sys
import types
from pathlib import Path

try:
    print("bmad-loop version:", importlib.metadata.version("bmad-loop"))
except importlib.metadata.PackageNotFoundError:
    print("bmad-loop version: <unavailable>")
if len(sys.argv) < 2:
    sys.exit("usage: smoke.py <project-root>")
PROJECT = Path(sys.argv[1]).resolve()
HERE = PROJECT / "tmp" / "bmad-loop-pi-smoke"
RUN = HERE / "run"
RUN.mkdir(parents=True, exist_ok=True)

from bmad_loop.adapters.base import SessionSpec
from bmad_loop.adapters.profile import CLIProfile, HookSpec
from bmad_loop_adapter_pi.pi_adapter import PiDevAdapter

# --- fabricate the engine-provided dependencies (only what the dev mixin touches)
limits = types.SimpleNamespace(
    dev_stall_grace_s=600,
    dev_stall_nudges=2,
    dev_contract_nudge=False,
)
policy = types.SimpleNamespace(limits=limits)
profile = CLIProfile(
    name="pi",
    binary="pi",
    adapter="pi",
    skill_tree=".agents/skills",
    prompt_template="Do exactly this and stop: {prompt}",
    bypass_args=["--approve"],
    model_flag="--model",
    hooks=HookSpec("none", "", {}),
)
impl = PROJECT / "_bmad-output" / "implementation-artifacts"
# BMAD's default output layout; if the project's bmad config redefines the
# implementation-artifacts dir, point this at it (the dev mixin globs it).
paths = types.SimpleNamespace(
    implementation_artifacts=impl,
    # The real ProjectPaths.artifact_at answers ONE Path (this session cwd's
    # rebased artifacts dir); the mixin globs it.
    artifact_at=lambda base, cwd: impl,
)

adapter = PiDevAdapter(
    run_dir=RUN,
    policy=policy,
    profile=profile,
    extra_args=(),
    usage_grace_s=1.0,
    stop_without_result_nudges=1,
    events_dir=None,
    paths=paths,
)

target = HERE / "hello.txt"
spec = SessionSpec(
    task_id="smoke-1",
    role="dev",
    prompt=f"Create the file {target} containing exactly the two characters OK, then stop.",
    cwd=PROJECT,
    env=dict(os.environ),
    timeout_s=600,
)

result = adapter.run(spec)
print("status:", result.status)
print("stop_seen:", result.stop_seen, "| session_id:", bool(result.session_id))
print("transcript:", result.transcript_path)
usage = adapter.read_usage(result)
print("usage:", usage)
hello = target.read_text() if target.exists() else "MISSING"
print("hello.txt:", hello)

ok = result.status in ("completed", "stalled") and hello.strip().upper() == "OK"
print("verdict:", "PASS (transport worked; expectations baseline is versioned — see header)" if ok
      else "FAIL (crashed or no artifact: read logs/smoke-1.pi.err; or re-derive expectations per references/seam-drift-audit.md)")
sys.exit(0 if ok else 1)
