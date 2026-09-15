"""Resume the existing authorized Cloud QA profile through the native Make target."""

import json
import os
from pathlib import Path
import subprocess


def main() -> None:
    artifact_directory = Path(__file__).resolve().parent
    repository = artifact_directory.parent.parent
    config = json.loads((artifact_directory / "session.json").read_text())
    local = json.loads((artifact_directory / "local-plugin-session.json").read_text())
    for value in (config["profile"], config["workspace"], local["electron_exec"], local["trust_file"]):
        path = Path(value)
        if not path.is_absolute() or not path.exists():
            raise ValueError("Missing existing isolated QA path")
    environment = dict(os.environ)
    environment.update(
        AGISTACK_DESKTOP_QA_PROFILE_DIR=config["profile"],
        AGISTACK_WORKSPACE_ROOT=config["workspace"],
        AGISTACK_DESKTOP_DEBUG_PORT="9334",
        AGISTACK_WEB_CONTROL_PLANE_ORIGIN="http://127.0.0.1:8000",
        AGISTACK_LOCAL_PLUGIN_TRUSTED_KEYS_FILE=local["trust_file"],
        ELECTRON_EXEC_PATH=local["electron_exec"],
    )
    subprocess.run(
        ["make", "-C", "agi-stack", "run-desktop"],
        cwd=repository,
        env=environment,
        check=True,
    )


if __name__ == "__main__":
    main()
