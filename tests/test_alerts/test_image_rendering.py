from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from alerts.components import (
    ContentType,
    FontSize,
    LineBreak,
    Map,
    Table,
    Text,
    render_components_image,
)


class TestRenderComponentsImage:
    @pytest.fixture
    def sample_components(self):
        """Create sample components for testing."""
        return [
            Text("Test Header", ContentType.IMPORTANT, FontSize.LARGE),
            LineBreak(),
            Map({"key1": "value1", "key2": "value2"}),
            LineBreak(),
            Table(
                rows=[
                    {"Name": "Alice", "Age": 30, "City": "New York"},
                    {"Name": "Bob", "Age": 25, "City": "San Francisco"},
                    {"Name": "Charlie", "Age": 35, "City": "Chicago"},
                ],
                title="Employee Data",
            ),
        ]

    @patch("alerts.components.imgkit.from_string")
    def test_render_components_image_basic(self, mock_imgkit, sample_components):
        """Test basic image rendering functionality."""

        # Mock imgkit to write test data to BytesIO
        def mock_imgkit_from_string(html_string, output, options=None):
            test_png_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xdb\x00\x00\x00\x00IEND\xaeB`\x82"
            output.write(test_png_data)

        mock_imgkit.side_effect = mock_imgkit_from_string

        result = render_components_image(sample_components)

        assert isinstance(result, BytesIO)
        assert result.tell() == 0  # Should be seeked to beginning

        # Verify imgkit was called with correct parameters
        mock_imgkit.assert_called_once()
        call_args = mock_imgkit.call_args
        assert isinstance(call_args[0][0], str)  # HTML string
        assert isinstance(call_args[0][1], BytesIO)  # Output BytesIO
        assert call_args[1]["options"] is not None  # Options dict

    @patch("alerts.components.imgkit.from_string")
    def test_render_components_image_options(self, mock_imgkit, sample_components):
        """Test that correct options are passed to imgkit."""
        mock_imgkit.return_value = None

        render_components_image(sample_components)

        call_args = mock_imgkit.call_args
        options = call_args[1]["options"]

        # Check expected options
        assert options["format"] == "png"
        assert options["encoding"] == "UTF-8"
        assert options["zoom"] == "2"
        assert options["quality"] == "100"
        assert options["quiet"] == ""

    @patch("alerts.components.imgkit.from_string")
    def test_render_components_image_empty_components(self, mock_imgkit):
        """Test rendering with empty components list."""
        mock_imgkit.return_value = None

        result = render_components_image([])

        assert isinstance(result, BytesIO)
        mock_imgkit.assert_called_once()

    @patch("alerts.components.imgkit.from_string")
    def test_render_components_image_single_component(self, mock_imgkit):
        """Test rendering with a single component."""
        mock_imgkit.return_value = None

        single_component = [Text("Single text", ContentType.INFO, FontSize.MEDIUM)]
        result = render_components_image(single_component)

        assert isinstance(result, BytesIO)
        mock_imgkit.assert_called_once()

    @patch("alerts.components.imgkit.from_string")
    def test_render_components_image_with_table(self, mock_imgkit):
        """Test rendering with table component."""
        mock_imgkit.return_value = None

        table_component = [
            Table(
                rows=[
                    {"Column A": "Value 1", "Column B": "Value 2"},
                    {"Column A": "Value 3", "Column B": "Value 4"},
                ],
                title="Test Table",
            )
        ]

        result = render_components_image(table_component)

        assert isinstance(result, BytesIO)
        mock_imgkit.assert_called_once()

    @patch("alerts.components.imgkit.from_string")
    def test_render_components_image_with_map(self, mock_imgkit):
        """Test rendering with map component."""
        mock_imgkit.return_value = None

        map_component = [
            Map(
                {"Setting 1": "Value 1", "Setting 2": "Value 2", "Setting 3": "Value 3"}
            )
        ]

        result = render_components_image(map_component)

        assert isinstance(result, BytesIO)
        mock_imgkit.assert_called_once()

    @patch("alerts.components.imgkit.from_string")
    def test_render_components_image_with_line_breaks(self, mock_imgkit):
        """Test rendering with line breaks."""
        mock_imgkit.return_value = None

        components_with_breaks = [
            Text("Line 1", ContentType.INFO, FontSize.SMALL),
            LineBreak(),
            Text("Line 2", ContentType.INFO, FontSize.SMALL),
            LineBreak(3),
            Text("Line 3 after multiple breaks", ContentType.INFO, FontSize.SMALL),
        ]

        result = render_components_image(components_with_breaks)

        assert isinstance(result, BytesIO)
        mock_imgkit.assert_called_once()

    @patch("alerts.components.imgkit.from_string")
    def test_render_components_image_mixed_content_types(self, mock_imgkit):
        """Test rendering with mixed content types and font sizes."""
        mock_imgkit.return_value = None

        mixed_components = [
            Text("Info text", ContentType.INFO, FontSize.SMALL),
            Text("Important text", ContentType.IMPORTANT, FontSize.MEDIUM),
            Text("Warning text", ContentType.WARNING, FontSize.SMALL),
            Text("Error text", ContentType.ERROR, FontSize.LARGE),
        ]

        result = render_components_image(mixed_components)

        assert isinstance(result, BytesIO)
        mock_imgkit.assert_called_once()

    @patch("alerts.components.imgkit.from_string")
    def test_render_components_image_html_content(self, mock_imgkit, sample_components):
        """Test that HTML content is properly passed to imgkit."""
        mock_imgkit.return_value = None

        render_components_image(sample_components)

        call_args = mock_imgkit.call_args
        html_content = call_args[0][0]

        # Check that HTML contains expected content
        assert isinstance(html_content, str)
        assert "Test Header" in html_content
        assert "Employee Data" in html_content
        assert "Alice" in html_content
        assert "key1" in html_content

    @patch("alerts.components.imgkit.from_string")
    def test_render_components_image_output_seek(self, mock_imgkit, sample_components):
        """Test that output BytesIO is properly seeked to beginning."""

        def mock_imgkit_from_string(html_string, output, options=None):
            # Write some data and move position
            output.write(b"test data")
            output.seek(10)  # Move to position 10

        mock_imgkit.side_effect = mock_imgkit_from_string

        result = render_components_image(sample_components)

        # Should be seeked back to beginning
        assert result.tell() == 0

    @patch("alerts.components.imgkit.from_string")
    def test_render_components_image_exception_handling(
        self, mock_imgkit, sample_components
    ):
        """Test handling of imgkit exceptions."""
        mock_imgkit.side_effect = Exception("imgkit error")

        with pytest.raises(Exception):
            render_components_image(sample_components)

    @patch("alerts.components.imgkit.from_string")
    def test_render_components_image_return_type(self, mock_imgkit, sample_components):
        """Test that the function returns the correct type."""
        mock_imgkit.return_value = None

        result = render_components_image(sample_components)

        assert isinstance(result, BytesIO)
        assert hasattr(result, "read")
        assert hasattr(result, "write")
        assert hasattr(result, "seek")
        assert hasattr(result, "tell")


class TestImageRenderingIntegration:
    """Integration tests for image rendering with real components."""

    @pytest.fixture
    def complex_components(self):
        """Create complex components for integration testing."""
        return [
            Text("System Status Report", ContentType.IMPORTANT, FontSize.LARGE),
            LineBreak(),
            Map(
                {
                    "Server": "Production",
                    "Status": "Online",
                    "Last Updated": "2025-01-16 10:30:00",
                    "CPU Usage": "45%",
                    "Memory Usage": "62%",
                }
            ),
            LineBreak(2),
            Table(
                rows=[
                    {
                        "Service": "Web Server",
                        "Status": "Running",
                        "Port": "80",
                        "CPU": "12%",
                    },
                    {
                        "Service": "Database",
                        "Status": "Running",
                        "Port": "5432",
                        "CPU": "28%",
                    },
                    {
                        "Service": "Redis",
                        "Status": "Running",
                        "Port": "6379",
                        "CPU": "3%",
                    },
                    {
                        "Service": "Message Queue",
                        "Status": "Running",
                        "Port": "5672",
                        "CPU": "8%",
                    },
                ],
                title="Service Status",
            ),
            LineBreak(),
            Text("All systems operational", ContentType.INFO, FontSize.MEDIUM),
        ]

    @patch("alerts.components.imgkit.from_string")
    def test_complex_components_render(self, mock_imgkit, complex_components):
        """Test rendering complex components combination."""
        mock_imgkit.return_value = None

        result = render_components_image(complex_components)

        assert isinstance(result, BytesIO)
        mock_imgkit.assert_called_once()

        # Check that HTML content contains all expected elements
        call_args = mock_imgkit.call_args
        html_content = call_args[0][0]

        assert "System Status Report" in html_content
        assert "Production" in html_content
        assert "Service Status" in html_content
        assert "Web Server" in html_content
        assert "All systems operational" in html_content
        assert "All systems operational" in html_content
