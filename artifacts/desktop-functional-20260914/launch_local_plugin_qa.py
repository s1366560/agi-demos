"""Launch this isolated QA instance through the repository's native Make target."""

import json
import os
from pathlib import Path
import subprocess


def main() -> None:
    artifact_directory = Path(__file__).resolve().parent
    repository = artifact_directory.parent.parent
    config = json.loads((artifact_directory / "local-plugin-session.json").read_text())
    for field in ("profile", "workspace", "trust_file", "electron_app", "electron_exec"):
        path = Path(config[field])
        if not path.is_absolute() or not path.exists():
            raise ValueError(f"Missing isolated QA path: {field}")
    environment = dict(os.environ)
    environment.update(
        AGISTACK_DESKTOP_QA_PROFILE_DIR=config["profile"],
        AGISTACK_WORKSPACE_ROOT=config["workspace"],
        AGISTACK_DESKTOP_DEBUG_PORT=str(config["debug_port"]),
        AGISTACK_WEB_CONTROL_PLANE_ORIGIN="http://127.0.0.1:8000",
        AGISTACK_LOCAL_PLUGIN_TRUSTED_KEYS_FILE=config["trust_file"],
        ELECTRON_EXEC_PATH=config["electron_exec"],
    )
    subprocess.run(
        ["make", "-C", "agi-stack", "run-desktop"],
        cwd=repository,
        env=environment,
        check=True,
    )


if __name__ == "__main__":
    main()
