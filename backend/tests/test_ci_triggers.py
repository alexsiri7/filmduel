"""Guard the CI trigger contract behind issue #739.

The daily build-drift check re-runs main CI with `gh workflow run ci.yml --ref main`,
so CI must accept manual dispatch, and a dispatched or re-run CI must never deploy:
every workflow reacting to CI completion may only deploy pushes.
"""

from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"


def _triggers(path: Path) -> dict:
    workflow = yaml.safe_load(path.read_text())
    # PyYAML reads the bare `on` key as the boolean True (YAML 1.1).
    return workflow.get("on", workflow.get(True)) or {}


def test_ci_accepts_manual_dispatch():
    assert "workflow_dispatch" in _triggers(WORKFLOWS / "ci.yml")


def test_ci_completion_consumers_deploy_only_pushes():
    consumers = [
        path
        for path in sorted(WORKFLOWS.glob("*.yml"))
        if "CI" in (_triggers(path).get("workflow_run") or {}).get("workflows", [])
    ]
    assert consumers, "expected a workflow_run consumer of CI (staging pipeline)"
    for path in consumers:
        assert "github.event.workflow_run.event == 'push'" in path.read_text(), (
            f"{path.name} reacts to CI completion without a push-only guard"
        )
