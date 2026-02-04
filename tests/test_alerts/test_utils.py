from io import StringIO

from taskflows.alerts import Table
from taskflows.alerts.utils import (
    Emoji,
    EmojiCycle,
    as_code_block,
    attach_tables,
    logger,
    price_dir_emoji,
    use_inline_tables,
)


def test_emoji_constants():
    """Test that emoji constants are defined."""
    assert hasattr(Emoji, "red_exclamation")
    assert hasattr(Emoji, "warning")
    assert hasattr(Emoji, "green_check")
    assert hasattr(Emoji, "red_circle")
    assert hasattr(Emoji, "green_circle")

    # Test that they are strings
    assert isinstance(Emoji.red_exclamation, str)
    assert isinstance(Emoji.warning, str)
    assert isinstance(Emoji.green_check, str)
    assert isinstance(Emoji.red_circle, str)
    assert isinstance(Emoji.green_circle, str)


def test_emoji_cycle():
    """Test EmojiCycle functionality."""
    cycle = EmojiCycle()

    # Test cycling through emojis
    emoji1 = cycle.next_emoji()
    emoji2 = cycle.next_emoji()
    emoji3 = cycle.next_emoji()

    # All should be valid emojis
    assert isinstance(emoji1, str)
    assert isinstance(emoji2, str)
    assert isinstance(emoji3, str)

    # Test group emoji functionality
    group_emoji1 = cycle.group_emoji("test_group")
    group_emoji2 = cycle.group_emoji("test_group")
    assert group_emoji1 == group_emoji2  # Should be consistent for same group


def test_price_dir_emoji():
    """Test price_dir_emoji function."""
    # Test positive change
    assert price_dir_emoji(1.0) == Emoji.green_circle
    assert price_dir_emoji(0.5) == Emoji.green_circle

    # Test negative change
    assert price_dir_emoji(-1.0) == Emoji.red_circle
    assert price_dir_emoji(-0.5) == Emoji.red_circle

    # Test zero change
    assert price_dir_emoji(0.0) == Emoji.green_circle


def test_as_code_block():
    """Test as_code_block function."""
    text = "test code"
    result = as_code_block(text)

    assert "```" in result
    assert text in result
    assert result.startswith("```")
    assert result.endswith("```")


def test_attach_tables():
    """Test attach_tables function."""
    # Create a table with many rows
    rows = [{"col": f"value_{i}"} for i in range(100)]
    table = Table(rows, title="Large Table")

    # Test with small max size (should return True to attach)
    result = attach_tables([table], attachments_max_size_mb=1)
    assert result is True

    # Test with large max size (should return True since table is small)
    result = attach_tables([table], attachments_max_size_mb=100)
    assert result is True

    # Test with empty list
    result = attach_tables([], attachments_max_size_mb=1)
    assert result is False


def test_use_inline_tables():
    """Test use_inline_tables function."""
    # Create a table with many rows
    rows = [{"col": f"value_{i}"} for i in range(100)]
    table = Table(rows, title="Large Table")

    # Test with small max rows (should return False to use inline)
    result = use_inline_tables([table], inline_tables_max_rows=10)
    assert result is False

    # Test with large max rows (should return True)
    result = use_inline_tables([table], inline_tables_max_rows=1000)
    assert result is True

    # Test with empty list
    result = use_inline_tables([], inline_tables_max_rows=10)
    assert result is True


def test_logger():
    """Test that logger is properly configured."""
    assert hasattr(logger, "info")
    assert hasattr(logger, "warning")
    assert hasattr(logger, "error")
    assert hasattr(logger, "debug")

    # Test that they are callable
    assert callable(logger.info)
    assert callable(logger.warning)
    assert callable(logger.error)
    assert callable(logger.debug)


def test_table_attach_rows_as_file():
    """Test Table.attach_rows_as_file method."""
    rows = [
        {"name": "Alice", "age": "30"},
        {"name": "Bob", "age": "25"},
        {"name": "Charlie", "age": "35"},
    ]
    table = Table(rows, title="Test Table")

    attachment_file = table.attach_rows_as_file()

    assert isinstance(attachment_file.filename, str)
    assert attachment_file.filename.endswith(".csv")
    assert "Test_Table" in attachment_file.filename

    assert isinstance(attachment_file.content, StringIO)

    # Read the file content
    content = attachment_file.read_content()

    assert "name,age" in content
    assert "Alice,30" in content
    assert "Bob,25" in content
    assert "Charlie,35" in content

    # Check that table rows are cleared
    assert table.rows is None
    assert table._attachment is not None


def test_table_attach_rows_as_file_no_title():
    """Test Table.attach_rows_as_file with no title."""
    rows = [{"col": "value"}]
    table = Table(rows)  # No title

    attachment_file = table.attach_rows_as_file()

    assert "table" in attachment_file.filename
    assert attachment_file.filename.endswith(".csv")


def test_table_attach_rows_as_file_long_title():
    """Test Table.attach_rows_as_file with long title."""
    long_title = "A" * 100  # Very long title
    rows = [{"col": "value"}]
    table = Table(rows, title=long_title)

    attachment_file = table.attach_rows_as_file()

    # Title should be truncated to 100 characters (default)
    assert len(attachment_file.filename.split("_")[0]) <= 100
    assert attachment_file.filename.endswith(".csv")


def test_price_dir_emoji_edge_cases():
    """Test price_dir_emoji with edge cases."""
    # Test very small positive
    assert price_dir_emoji(0.001) == Emoji.green_circle

    # Test very small negative
    assert price_dir_emoji(-0.001) == Emoji.red_circle

    # Test very large values
    assert price_dir_emoji(1000.0) == Emoji.green_circle
    assert price_dir_emoji(-1000.0) == Emoji.red_circle


def test_as_code_block_empty():
    """Test as_code_block with empty string."""
    result = as_code_block("")
    assert result == "```\n```"


def test_as_code_block_multiline():
    """Test as_code_block with multiline text."""
    text = "line 1\nline 2\nline 3"
    result = as_code_block(text)

    assert "```" in result
    assert "line 1" in result
    assert "line 2" in result
    assert "line 3" in result
    assert result.count("```") == 2  # Opening and closing
