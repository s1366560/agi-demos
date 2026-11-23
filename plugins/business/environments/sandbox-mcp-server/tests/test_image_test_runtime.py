"""The delivered image venv includes pytest and pytest-cov at build time."""

from pathlib import Path


def test_image_venv_installs_test_runtime_from_the_wheelhouse() -> None:
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    project = (root / "pyproject.toml").read_text(encoding="utf-8")
    entrypoint = (root / "scripts" / "entrypoint.sh").read_text(encoding="utf-8")

    assert 'pip wheel --no-cache-dir --wheel-dir /wheelhouse ".[test-runtime]"' in dockerfile
    assert '"sandbox-mcp-server[test-runtime]==0.1.0"' in dockerfile
    assert "--no-index" in dockerfile
    assert "test-runtime" in project
    assert "pytest>=" in project
    assert "pytest-cov>=" in project
    assert "pip install" not in entrypoint
