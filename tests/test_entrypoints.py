from unittest.mock import MagicMock, patch

import click
import pytest

from taskflows.entrypoints import ShutdownHandler, parse_str_kwargs


def test_parse_str_kwargs_preserves_ints_and_parses_signed_numbers():
    assert parse_str_kwargs(
        [
            "workers=4",
            "threshold=-0.25",
            "ratio=1.5",
            "label=prod-1",
        ]
    ) == {
        "workers": 4,
        "threshold": -0.25,
        "ratio": 1.5,
        "label": "prod-1",
    }


@pytest.mark.parametrize("pair", ["missing_equals", "=value", "key="])
def test_parse_str_kwargs_rejects_malformed_pairs(pair):
    with pytest.raises(click.BadParameter):
        parse_str_kwargs([pair])


def test_shutdown_handler_falls_back_when_loop_signal_handlers_are_unavailable():
    loop = MagicMock()
    loop.add_signal_handler.side_effect = NotImplementedError
    with (
        patch("taskflows.entrypoints.asyncio.new_event_loop", return_value=loop),
        patch("taskflows.entrypoints.asyncio.set_event_loop"),
        patch("taskflows.entrypoints.signal.signal") as register,
    ):
        ShutdownHandler()
    assert register.called
