"""Contract tests for scripts/utils/with-env.sh environment resolution.

with-env.sh is the single source of truth for resolving the tenant knobs
(ENVIRONMENT, PROJECT_NAME, AWS_REGION). The contract: it loads .env as the
base layer, and a value already set in the environment (a per-command
``ENVIRONMENT=demo task …`` override) wins over the file.

These run offline: the account guard only makes an AWS call when AWS_ACCOUNT_ID
is set, so the tests unset it (and AWS_PROFILE) to keep resolution local.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WITH_ENV = REPO_ROOT / "scripts" / "utils" / "with-env.sh"

BASE_ENV_VARS = {"ENVIRONMENT": "dev", "PROJECT_NAME": "base-proj", "AWS_REGION": "us-west-2"}


def _env_body(env_vars: dict[str, str]) -> str:
    """Render a dotenv file body from a mapping."""
    return "".join(f"{k}={v}\n" for k, v in env_vars.items())


def _resolve(
    tmp_path: Path, overrides: dict[str, str], env_vars: dict[str, str] | None = None
) -> dict[str, str]:
    """Source with-env.sh in a throwaway repo root and report the resolved knobs.

    Creates a minimal repo root (Taskfile.yml marker + .env) in ``tmp_path``,
    sources the real with-env.sh from there with ``overrides`` applied to the
    environment, and returns the resolved ENVIRONMENT/PROJECT_NAME/AWS_REGION.

    Raises:
        AssertionError: if the helper exits non-zero (its own failure mode).
    """
    (tmp_path / "Taskfile.yml").write_text("version: '3'\n")
    (tmp_path / ".env").write_text(_env_body(env_vars or BASE_ENV_VARS))

    # Start from a clean slate: unset the knobs (and guard inputs) so only the
    # explicit overrides model a per-command invocation. AWS_ACCOUNT_ID unset →
    # account guard skipped (no AWS call).
    exports = "".join(f"export {k}={v}\n" for k, v in overrides.items())
    script = (
        "set -e\n"
        "unset AWS_ACCOUNT_ID AWS_PROFILE ENVIRONMENT PROJECT_NAME AWS_REGION\n"
        f"{exports}"
        f"cd {tmp_path}\n"
        f"source {WITH_ENV} >/dev/null 2>&1\n"
        'printf "%s\\n%s\\n%s\\n" "$ENVIRONMENT" "$PROJECT_NAME" "$AWS_REGION"\n'
    )
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)
    assert result.returncode == 0, f"with-env.sh failed: {result.stderr}"
    env_v, proj_v, region_v = result.stdout.strip().split("\n")
    return {"ENVIRONMENT": env_v, "PROJECT_NAME": proj_v, "AWS_REGION": region_v}


def _resolve_var(
    tmp_path: Path, var: str, overrides: dict[str, str], env_vars: dict[str, str] | None = None
) -> str:
    """Source with-env.sh and report a single exported variable's value.

    Mirrors ``_resolve`` but prints one named variable, so tests can assert on
    derived exports (e.g. AWS_DEFAULT_REGION) that the helper sets beyond the
    three core knobs.

    Raises:
        AssertionError: if the helper exits non-zero (its own failure mode).
    """
    (tmp_path / "Taskfile.yml").write_text("version: '3'\n")
    (tmp_path / ".env").write_text(_env_body(env_vars or BASE_ENV_VARS))

    exports = "".join(f"export {k}={v}\n" for k, v in overrides.items())
    script = (
        "set -e\n"
        "unset AWS_ACCOUNT_ID AWS_PROFILE ENVIRONMENT PROJECT_NAME AWS_REGION AWS_DEFAULT_REGION\n"
        f"{exports}"
        f"cd {tmp_path}\n"
        f"source {WITH_ENV} >/dev/null 2>&1\n"
        f'printf "%s" "${{{var}}}"\n'
    )
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)
    assert result.returncode == 0, f"with-env.sh failed: {result.stderr}"
    return result.stdout


class TestWithEnvPrecedence:
    def test_no_override_uses_env_file(self, tmp_path: Path) -> None:
        resolved = _resolve(tmp_path, overrides={})
        assert resolved == {
            "ENVIRONMENT": "dev",
            "PROJECT_NAME": "base-proj",
            "AWS_REGION": "us-west-2",
        }

    def test_environment_override_wins(self, tmp_path: Path) -> None:
        resolved = _resolve(tmp_path, overrides={"ENVIRONMENT": "demo"})
        assert resolved["ENVIRONMENT"] == "demo"
        # Non-overridden knobs still come from the file.
        assert resolved["PROJECT_NAME"] == "base-proj"

    def test_all_three_knobs_override_wins(self, tmp_path: Path) -> None:
        resolved = _resolve(
            tmp_path,
            overrides={
                "ENVIRONMENT": "demo",
                "PROJECT_NAME": "aw-region-test",
                "AWS_REGION": "ap-southeast-2",
            },
        )
        assert resolved == {
            "ENVIRONMENT": "demo",
            "PROJECT_NAME": "aw-region-test",
            "AWS_REGION": "ap-southeast-2",
        }

    def test_empty_environment_is_fatal(self, tmp_path: Path) -> None:
        # No ENVIRONMENT in the file and none in the environment → loud exit.
        (tmp_path / "Taskfile.yml").write_text("version: '3'\n")
        (tmp_path / ".env").write_text(_env_body({"PROJECT_NAME": "base-proj", "AWS_REGION": "x"}))
        script = f"unset AWS_ACCOUNT_ID AWS_PROFILE ENVIRONMENT\ncd {tmp_path}\nsource {WITH_ENV}\n"
        result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)
        assert result.returncode != 0
        assert "No environment selected" in result.stderr


class TestWithEnvAwsDefaultRegion:
    """botocore reads AWS_DEFAULT_REGION, not AWS_REGION; the helper must export
    both from the single AWS_REGION knob so boto3-based tools (the agentcore
    toolkit) honor the region override instead of the profile's region."""

    def test_aws_default_region_mirrors_aws_region_from_file(self, tmp_path: Path) -> None:
        assert _resolve_var(tmp_path, "AWS_DEFAULT_REGION", overrides={}) == "us-west-2"

    def test_aws_default_region_follows_region_override(self, tmp_path: Path) -> None:
        # The R4 failure mode: a per-command AWS_REGION override must propagate to
        # AWS_DEFAULT_REGION, or botocore silently uses the profile's region.
        resolved = _resolve_var(
            tmp_path, "AWS_DEFAULT_REGION", overrides={"AWS_REGION": "ap-southeast-2"}
        )
        assert resolved == "ap-southeast-2"
