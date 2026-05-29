"""Run a local, repeatable Darwinian Evolver parrot evaluation.

This script starts a tiny OpenAI-compatible fake chat endpoint, runs the plugin's
OpenRouter parrot driver against it, reads the resulting snapshot, and optionally
checks the Hermes reference snapshot reader against the same file.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar


class _FakeOpenAIHandler(BaseHTTPRequestHandler):
    """OpenAI-compatible endpoint with deterministic improvement behavior."""

    request_count = 0
    prompts: ClassVar[list[str]] = []

    def do_POST(self) -> None:
        type(self).request_count += 1
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        prompt = str(payload.get("messages", [{}])[-1].get("content", ""))
        type(self).prompts.append(prompt)

        if (
            "propose an improved prompt template" in prompt
            or "Return only the improved template" in prompt
        ):
            content = "Use the phrase exactly.\n```\n{{ phrase }}\n```"
        elif prompt.startswith("Say "):
            content = "not exact"
        else:
            content = prompt

        body = {
            "id": "fake-chatcmpl",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
        }
        raw = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *_args: object) -> None:
        return


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--de-dir",
        type=Path,
        default=Path(
            os.environ.get("DARWINIAN_EVOLVER_CACHE_DIR", "~/.memstack/cache/darwinian-evolver")
        ).expanduser()
        / "darwinian_evolver",
        help="Path to the upstream darwinian_evolver checkout.",
    )
    parser.add_argument(
        "--plugin-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Path to this darwinian-evolver skill directory.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/tmp/memstack_darwinian_evolver_eval"),
        help="Directory for run artifacts.",
    )
    parser.add_argument("--iterations", type=int, default=2)
    parser.add_argument("--hermes-skill-dir", type=Path, default=None)
    args = parser.parse_args()

    if not args.de_dir.exists():
        sys.exit(f"missing upstream checkout: {args.de_dir}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    run_dir = args.output_dir / "parrot"
    shutil.rmtree(run_dir, ignore_errors=True)

    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeOpenAIHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{server.server_port}/v1"
    env = dict(os.environ)
    env.update(
        {
            "OPENROUTER_API_KEY": "local-fake-key",
            "OPENROUTER_BASE_URL": base_url,
            "EVOLVER_MODEL": "local/fake",
        }
    )

    try:
        driver_result = _run(
            [
                "uv",
                "run",
                "--with",
                "openai",
                "python",
                str(args.plugin_dir / "scripts" / "parrot_openrouter.py"),
                "--num_iterations",
                str(args.iterations),
                "--num_parents_per_iteration",
                "1",
                "--mutator_concurrency",
                "1",
                "--evaluator_concurrency",
                "1",
                "--output_dir",
                str(run_dir),
            ],
            cwd=args.de_dir,
            env=env,
        )

        snapshot_path = run_dir / "snapshots" / f"iteration_{args.iterations}.pkl"
        show_result = _run(
            [
                "uv",
                "run",
                "--with",
                "openai",
                "python",
                str(args.plugin_dir / "scripts" / "show_snapshot.py"),
                str(snapshot_path),
                "--i-trust-this-file",
                "--top",
                "2",
            ],
            cwd=args.de_dir,
            env=env,
        )

        hermes_result: dict[str, object] | None = None
        if args.hermes_skill_dir is not None:
            hermes_result = _run(
                [
                    "uv",
                    "run",
                    "--with",
                    "openai",
                    "python",
                    str(args.hermes_skill_dir / "scripts" / "show_snapshot.py"),
                    str(snapshot_path),
                    "--i-trust-this-file",
                    "--top",
                    "2",
                ],
                cwd=args.de_dir,
                env=env,
            )

        report = {
            "driver_exit": driver_result["returncode"],
            "snapshot_exit": show_result["returncode"],
            "hermes_snapshot_exit": None if hermes_result is None else hermes_result["returncode"],
            "best_scores": _read_best_scores(run_dir / "results.jsonl"),
            "fake_request_count": _FakeOpenAIHandler.request_count,
            "output_dir": str(run_dir),
            "snapshot": str(snapshot_path),
            "driver_stdout": driver_result["stdout"],
            "snapshot_stdout": show_result["stdout"],
            "hermes_snapshot_stderr": None if hermes_result is None else hermes_result["stderr"],
        }
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if driver_result["returncode"] == 0 and show_result["returncode"] == 0 else 1
    finally:
        server.shutdown()


def _run(cmd: list[str], *, cwd: Path, env: dict[str, str]) -> dict[str, object]:
    result = subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True, check=False)
    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _read_best_scores(path: Path) -> list[float]:
    scores: list[float] = []
    if not path.exists():
        return scores
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        scores.append(float(payload["best_score"]))
    return scores


if __name__ == "__main__":
    raise SystemExit(main())
