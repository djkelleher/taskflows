import click
import pytest

from taskflows.entrypoints import parse_str_kwargs


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
