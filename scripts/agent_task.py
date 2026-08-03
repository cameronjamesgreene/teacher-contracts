"""Minimal file-based task queue letting a coding agent (Claude Code, Codex, etc.)
perform LLM-style extraction itself, with no API key required.

Call `run_task(task_id, instructions, input_text, task_dir)` wherever a script would
otherwise call an LLM API. If a response for that task_id already exists, it is
returned immediately (this is also the resume/cache mechanism). Otherwise the
instructions and input are written to a task file and the function raises
AgentTaskPending. The calling script should let that propagate to the top level,
print the task path, and exit. The agent then:
  1. Reads the task file (and any listed page images, for vision tasks).
  2. Produces the JSON answer the instructions ask for.
  3. Writes that JSON, and nothing else, to the response path named in the task file.
  4. Re-runs the script to continue with the next task.
"""

from __future__ import annotations

import json
from pathlib import Path


class AgentTaskPending(Exception):
    def __init__(self, task_id: str, task_path: Path, response_path: Path):
        self.task_id = task_id
        self.task_path = task_path
        self.response_path = response_path
        super().__init__(f"Task pending: {task_id} -> {task_path}")


def run_task(
    task_id: str,
    instructions: str,
    input_text: str,
    task_dir: Path,
    image_paths: list[Path] | None = None,
) -> dict:
    task_dir.mkdir(parents=True, exist_ok=True)
    response_path = task_dir / f"{task_id}.response.json"
    if response_path.exists():
        return json.loads(response_path.read_text(encoding="utf-8"))

    task_path = task_dir / f"{task_id}.task.md"
    lines = [
        f"# Task: {task_id}",
        "",
        "## Instructions",
        instructions,
        "",
        "## Input",
        input_text,
    ]
    if image_paths:
        lines += ["", "## Page image(s) — read each of these with your file-reading tool:"]
        lines += [f"- {p}" for p in image_paths]
    lines += [
        "",
        "## What to do",
        "Read the instructions and input above" + (" and the page image(s) listed" if image_paths else "")
        + ". Produce the JSON answer they ask for, then write it — and nothing else — to:",
        f"`{response_path}`",
        "Then re-run the script that printed this task to continue.",
    ]
    task_path.write_text("\n".join(lines), encoding="utf-8")
    raise AgentTaskPending(task_id, task_path, response_path)
