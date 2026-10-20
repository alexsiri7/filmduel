"""Guard the CI supply-chain integrity contract behind issue #795.

Workflows hold deploy tokens, so every action they run must be pinned to an immutable
commit, and the Railway CLI the deploy jobs execute must be checksum-verified before use.
"""

import re
from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
STAGING_PIPELINE = WORKFLOWS / "staging-pipeline.yml"
PINNED_ACTION = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def _uses(workflow: dict) -> list[str]:
    """Every action or reusable workflow a workflow references, at job or step level."""
    jobs = workflow["jobs"].values()
    owners = [*jobs, *(step for job in jobs for step in job.get("steps", []))]
    return [owner["uses"] for owner in owners if "uses" in owner]


def test_every_action_is_sha_pinned():
    refs = [
        (path.name, ref)
        for path in sorted(WORKFLOWS.glob("*.y*ml"))
        for ref in _uses(_load(path))
    ]
    assert refs, "expected workflows to use actions"
    unpinned = [f"{name}: {ref}" for name, ref in refs if not PINNED_ACTION.match(ref)]
    assert not unpinned, f"actions not pinned to a full commit SHA: {unpinned}"


def test_railway_cli_is_verified_before_use():
    workflow = _load(STAGING_PIPELINE)
    assert re.fullmatch(r"[0-9a-f]{64}", workflow["env"]["RAILWAY_CLI_SHA256"])
    installs = {
        job_name: (job, step)
        for job_name, job in workflow["jobs"].items()
        for step in job.get("steps", [])
        if step.get("name") == "Install Railway CLI"
    }
    assert set(installs) == {"deploy-staging", "deploy-production"}
    for job_name, (job, step) in installs.items():
        overrides = {"RAILWAY_CLI_VERSION", "RAILWAY_CLI_SHA256"} & (
            set(job.get("env") or {}) | set(step.get("env") or {})
        )
        assert not overrides, f"{job_name} shadows the shared Railway CLI pin: {overrides}"
        lines = step["run"].splitlines()
        verify = next(
            (i for i, line in enumerate(lines)
             if "sha256sum -c" in line and "${RAILWAY_CLI_SHA256}" in line),
            None,
        )
        assert verify is not None, f"{job_name} installs Railway CLI without sha256sum -c"
        first_use = next(i for i, line in enumerate(lines) if "tar " in line)
        assert verify < first_use, f"{job_name} extracts Railway CLI before verifying it"
