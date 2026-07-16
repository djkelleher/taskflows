from pathlib import Path

import pytest

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"


@pytest.fixture
def snapshot(request):
    """Compare a string against a golden file in tests/snapshots/.

    Regenerate golden files by running pytest with --update-snapshots.
    """

    def check(name: str, content: str) -> None:
        path = SNAPSHOT_DIR / name
        if request.config.getoption("--update-snapshots"):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            return
        assert path.exists(), (
            f"Missing snapshot {path}. Run `pytest --update-snapshots` to create it."
        )
        expected = path.read_text()
        assert content == expected, (
            f"Rendered output does not match snapshot {path}. If the change is "
            "intentional, regenerate with `pytest --update-snapshots`."
        )

    return check


def pytest_addoption(parser):
    parser.addoption(
        "--update-snapshots",
        action="store_true",
        default=False,
        help="Rewrite golden snapshot files instead of comparing against them.",
    )
