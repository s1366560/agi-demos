from scripts.ci_path_filter import classify


def test_docs_only_skips_expensive_jobs() -> None:
    assert classify(["docs/guide.md", "README.md"]) == {
        "backend": False,
        "web": False,
        "agi": False,
    }


def test_web_change_does_not_run_the_desktop_stack() -> None:
    assert classify(["web/src/App.tsx"]) == {
        "backend": False,
        "web": True,
        "agi": False,
    }


def test_unknown_path_fails_open() -> None:
    assert classify(["third_party/avernet-bcs/Cargo.toml"]) == {
        "backend": True,
        "web": True,
        "agi": True,
    }


def test_empty_diff_fails_open() -> None:
    assert classify([]) == {"backend": True, "web": True, "agi": True}
