import random
from pathlib import Path
from uuid import uuid4

import pytest
from taskflows.alerts import ContentType, FontSize, Map, Table, Text


def pytest_addoption(parser):
    parser.addoption(
        "--email-addr",
        action="store",
        help="Email address to send/receive test email.",
    )
    parser.addoption(
        "--email-pass",
        action="store",
        help="Password for Email login.",
    )
    parser.addoption(
        "--slack-bot-token",
        action="store",
        help="Slack bot token.",
    )
    parser.addoption(
        "--slack-channel",
        action="store",
        help="Slack channel.",
    )
    parser.addoption(
        "--discord-webhook",
        action="store",
        help="Discord webhook URL.",
    )
    parser.addoption(
        "--test-output",
        action="store",
        help="Output directory for saving test HTML, markdown, and image files.",
    )


@pytest.fixture
def output_dir(request):
    """Fixture to provide output directory for saving test files."""
    output_path = request.config.getoption("--test-output")
    if output_path:
        path = Path(output_path)
        path.mkdir(parents=True, exist_ok=True)
        return path


@pytest.fixture
def components():
    return [
        Text(
            " ".join(["Test Text." for _ in range(5)]),
            ContentType.IMPORTANT,
            FontSize.LARGE,
        ),
        Map({f"TestKey{i}": f"TestValue{i}" for i in range(5)}),
        Table(
            rows=[
                {
                    "TestStrColumn": str(uuid4()),
                    "TestIntColumn": random.randint(0, 5),
                    "TestBoolColumn": random.choice([True, False]),
                }
                for _ in range(10)
            ],
            title=" ".join(["Test Caption." for _ in range(5)]),
        ),
    ]
