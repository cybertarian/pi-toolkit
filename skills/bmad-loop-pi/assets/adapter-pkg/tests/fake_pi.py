#!/usr/bin/env python
"""Deterministic stand-in for `pi -p` (print mode), for adapter tests.

Emulates the parts of the pi CLI the bmad-loop pi adapter depends on:

- accepts pi-shaped argv: ``-p <prompt>`` and ignores unknown flags
  (``--approve``, ``--model X``, profile extra_args all pass through);
- writes the pi session JSONL (header + one assistant message carrying
  ``usage`` + one ``usage`` entry) to ``<session-dir>/<ts>_<session-id>.jsonl``
  with the exact layout ``pi --session-dir`` produces;
- optional side effects, each gated on an env var the test sets in the
  spawn env (the engine passes spec.env to the process, mirroring how a
  real bmad-loop session receives the BMAD_LOOP_* contract):
  * ``FAKE_PI_RESULT=<path>``   write a dev-skill result.json there;
  * ``FAKE_PI_SPEC=<path>``     write a terminal story spec there
    (frontmatter ``status: done`` + a ``## Auto Run Result`` marker);
  * ``FAKE_PI_RC=<int>``        exit code (default 0).

No network, no LLM, no sleeps: instant and deterministic.
"""

import json
import os
import sys
from pathlib import Path


def main() -> int:
    args = sys.argv[1:]
    # Parse just enough of pi's argv to mirror its observable behavior.
    session_dir = None
    session_id = "fake"
    i = 0
    while i < len(args):
        a = args[i]
        if a == "-p" and i + 1 < len(args):
            i += 2  # consume prompt
        elif a in ("--approve",):
            i += 1
        elif a in ("--session-dir", "--session-id") and i + 1 < len(args):
            if a == "--session-dir":
                session_dir = Path(args[i + 1])
            else:
                session_id = args[i + 1]
            i += 2
        elif a in ("--model",) and i + 1 < len(args):
            i += 2
        else:
            i += 1  # unknown flag or its value: irrelevant to the emulation

    # Session file: pi writes `<session-dir>/<timestamp>_<session-id>.jsonl`.
    if session_dir is not None:
        session_dir.mkdir(parents=True, exist_ok=True)
        stamp = "2026-01-01T00-00-00-000Z"
        session_file = session_dir / f"{stamp}_{session_id}.jsonl"
        rows = [
            {"type": "session", "version": 3, "id": session_id, "cwd": os.getcwd()},
            {
                "type": "message",
                "id": "a0",
                "parentId": None,
                "message": {
                    "role": "assistant",
                    "model": "fake/model",
                    "usage": {"input": 1000, "output": 10, "cacheRead": 500, "cacheWrite": 0},
                },
            },
            # A non-conversation usage entry (pi counts these toward session totals).
            {
                "type": "usage",
                "id": "u0",
                "kind": "cache_warm",
                "usage": {"input": 0, "output": 0, "cacheRead": 250, "cacheWrite": 50},
            },
        ]
        with session_file.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row) + "\n")

    result = os.environ.get("FAKE_PI_RESULT")
    if result:
        p = Path(result)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"status": "done", "detail": "fake dev result"}), encoding="utf-8")

    spec = os.environ.get("FAKE_PI_SPEC")
    if spec:
        sp = Path(spec)
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(
            "---\n"
            "status: done\n"
            "title: fake story\n"
            "---\n"
            "\n"
            "# Fake Story\n"
            "\n"
            "Body.\n"
            "\n"
            "## Auto Run Result\n"
            "\n"
            "**Status:** done\n"
            "Deterministic fake terminal marker for adapter tests.\n",
            encoding="utf-8",
        )

    return int(os.environ.get("FAKE_PI_RC", "0"))


if __name__ == "__main__":
    sys.exit(main())
