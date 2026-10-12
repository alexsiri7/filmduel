"""Guard the CI trigger contract behind issue #739.

The daily build-drift check re-runs main CI with `gh workflow run ci.yml --ref main`,
so CI must accept manual dispatch, and a dispatched or re-run CI must never deploy:
every workflow reacting to CI completion may only deploy pushes.
"""

from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
PUSH_GUARD = "github.event.workflow_run.event == 'push'"
MANUAL_ONLY = "github.event_name == 'workflow_dispatch'"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def _triggers(workflow: dict) -> dict:
    # PyYAML reads the bare `on` key as the boolean True (YAML 1.1).
    return workflow.get("on", workflow.get(True)) or {}


def _split_top_level(expr: str, operator: str) -> list[str]:
    parts, depth, start = [], 0, 0
    for i, char in enumerate(expr):
        depth += {"(": 1, ")": -1}.get(char, 0)
        if depth == 0 and expr.startswith(operator, i):
            parts.append(expr[start:i])
            start = i + len(operator)
    parts.append(expr[start:])
    return [_unwrap(part) for part in parts]


def _unwrap(expr: str) -> str:
    expr = " ".join(expr.split())
    while expr.startswith("(") and _closing_paren(expr) == len(expr) - 1:
        expr = expr[1:-1].strip()
    return expr


def _closing_paren(expr: str) -> int:
    depth = 0
    for i, char in enumerate(expr):
        depth += {"(": 1, ")": -1}.get(char, 0)
        if depth == 0:
            return i
    return -1


def _admits_only_pushes(condition: str) -> bool:
    """Every branch of the condition a CI completion can satisfy requires a push."""
    for branch in _split_top_level(condition, "||"):
        conjuncts = _split_top_level(branch, "&&")
        if MANUAL_ONLY not in conjuncts and PUSH_GUARD not in conjuncts:
            return False
    return True


def _push_gated_jobs(jobs: dict) -> set[str]:
    """Jobs whose own `if:` admits only pushes, or that implicitly skip with a gated need."""
    gated: set[str] = set()
    while True:
        newly = {
            name
            for name, job in jobs.items()
            if name not in gated
            and (
                _admits_only_pushes(str(job["if"]))
                if "if" in job
                else any(need in gated for need in _needs(job))
            )
        }
        if not newly:
            return gated
        gated |= newly


def _needs(job: dict) -> list[str]:
    needs = job.get("needs", [])
    return [needs] if isinstance(needs, str) else needs


def test_ci_accepts_manual_dispatch():
    assert "workflow_dispatch" in _triggers(_load(WORKFLOWS / "ci.yml"))


def test_ci_completion_consumers_deploy_only_pushes():
    ci_name = _load(WORKFLOWS / "ci.yml")["name"]
    consumers = {
        path.name: workflow
        for path in sorted(WORKFLOWS.glob("*.y*ml"))
        if ci_name in (_triggers(workflow := _load(path)).get("workflow_run") or {}).get("workflows", [])
    }
    assert consumers, f"expected a workflow_run consumer of {ci_name!r} (staging pipeline)"
    for name, workflow in consumers.items():
        ungated = set(workflow["jobs"]) - _push_gated_jobs(workflow["jobs"])
        assert not ungated, f"{name} jobs {sorted(ungated)} can run on a non-push CI completion"


def test_push_guard_must_be_conjoined():
    assert _admits_only_pushes(f"({MANUAL_ONLY} && x) || (a == 'success' && {PUSH_GUARD})")
    assert not _admits_only_pushes(f"a == 'success' || {PUSH_GUARD}")
    assert not _admits_only_pushes(f"a == 'success' && (b || {PUSH_GUARD})")
    assert not _admits_only_pushes("always()")
