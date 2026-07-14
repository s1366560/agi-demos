from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
MAKEFILE = REPO_ROOT / "Makefile"


def _makefile_text() -> str:
    return MAKEFILE.read_text(encoding="utf-8")


def _target_block(text: str, target: str) -> str:
    start = text.index(f"{target}:")
    remaining = text[start:].splitlines()
    block = [remaining[0]]

    for line in remaining[1:]:
        if line and not line[0].isspace() and not line.startswith("#"):
            break
        block.append(line)

    return "\n".join(block)


def test_restart_serializes_stop_before_dev() -> None:
    restart = _target_block(_makefile_text(), "restart")

    assert "restart: ##" in restart
    assert restart.index("$(MAKE) stop") < restart.index("$(MAKE) dev")


def test_dev_stop_only_terminates_listening_processes() -> None:
    dev_stop = _target_block(_makefile_text(), "dev-stop")

    assert "lsof -tiTCP:$$port -sTCP:LISTEN" in dev_stop
    assert "lsof -ti :$$port" not in dev_stop


def test_dev_all_waits_for_api_before_starting_web() -> None:
    dev_all = _target_block(_makefile_text(), "dev-all")

    api_start = dev_all.index("uv run uvicorn")
    api_ready = dev_all.index("curl -fsS http://127.0.0.1:8000/health")
    web_start = dev_all.index("$(WEB_DEV_CMD)")
    web_ready = dev_all.index("curl -fsS http://127.0.0.1:3000/")

    assert api_start < api_ready < web_start < web_ready


def test_background_services_do_not_inherit_make_jobserver_fds() -> None:
    dev_all = _target_block(_makefile_text(), "dev-all")

    assert dev_all.count("3>&- 4>&-") >= 2
