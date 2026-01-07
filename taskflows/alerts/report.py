import asyncio
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from typing import List as ListType
from typing import Optional, Sequence, Union

import imgkit
from dominate import tags as d

from .components import Component, Text, get_theme_colors


class Report:
    """A container for message components with convenient rendering methods."""

    def __init__(
        self, *components: Union[Component, str, Sequence[Union[Component, str]]]
    ):
        """
        Args:
            *components: Initial component(s) to add to the report. Can be:
                - Multiple components as arguments: Report(comp1, comp2, comp3)
                - A single list: Report([comp1, comp2, comp3])
                - Nothing: Report()
        """
        if len(components) == 0:
            self.components: ListType[Component] = []
        elif len(components) == 1 and isinstance(components[0], (list, tuple)):
            # Single list/tuple argument - unpack it
            self.components = _components_list(components[0])
        else:
            # Multiple arguments or single non-list argument
            self.components = _components_list(components)

    def add(
        self, *components: Union[Component, str, Sequence[Union[Component, str]]]
    ) -> "Report":
        """Add one or more components to the report.

        Args:
            *components: Component(s) to add. Can be:
                - Multiple components as arguments: add(comp1, comp2, comp3)
                - A single list: add([comp1, comp2, comp3])

        Returns:
            Self for method chaining.
        """
        if len(components) == 1 and isinstance(components[0], (list, tuple)):
            # Single list/tuple argument - unpack it
            new_components = _components_list(components[0])
        else:
            # Multiple arguments or single non-list argument
            new_components = _components_list(components)
        self.components.extend(new_components)
        return self

    def html(self, theme: str = "dark") -> str:
        """Render the report as HTML.

        Args:
            theme: The theme to use ('light' or 'dark'). Defaults to 'dark'.

        Returns:
            str: The rendered HTML.
        """
        return render_components_html(self.components, theme=theme)

    def image(self, theme: str = "dark") -> BytesIO:
        """Render the report as a PNG image (synchronous).

        Args:
            theme: The theme to use ('light' or 'dark'). Defaults to 'dark'.

        Returns:
            BytesIO: The image data as bytes.
        """
        return render_components_image(self.components, theme=theme)

    async def image_async(
        self, theme: str = "dark", executor: Optional[ThreadPoolExecutor] = None
    ) -> BytesIO:
        """Render the report as a PNG image (asynchronous).

        Args:
            theme: The theme to use ('light' or 'dark'). Defaults to 'dark'.
            executor: Optional ThreadPoolExecutor to use.

        Returns:
            BytesIO: The image data as bytes.
        """
        return await render_components_image_async(
            self.components, theme=theme, executor=executor
        )

    def md(self, slack_format: bool = False, discord_format: bool = False) -> str:
        """Render the report as Markdown.

        Args:
            slack_format: Use Slack's subset of Markdown features. Defaults to False.
            discord_format: Use Discord's markdown features. Defaults to False.

        Returns:
            str: The rendered Markdown.
        """
        return render_components_md(
            self.components, slack_format=slack_format, discord_format=discord_format
        )


def render_components_html(components: Sequence[Component], theme: str = "dark") -> str:
    """Render components as HTML with theme support.

    Args:
        components: The components to render.
        theme: The theme to use ('light' or 'dark'). Defaults to 'dark'.
    """
    colors = get_theme_colors(theme)

    with d.html() as doc:
        with d.head():
            d.title("Components")
        with d.body(
            style=f"font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; padding: 20px; background-color: {colors['page_bg']};"
        ):
            with d.div(
                style=f"width: fit-content; margin: 0 auto; background-color: {colors['container_bg']}; padding: 20px; border-radius: 8px; color: {colors['text_primary']};"
            ) as container:
                for component in _components_list(components):
                    container.add(component.html(theme=theme))
    return doc.render()


def render_components_image(
    components: Sequence[Component], theme: str = "dark"
) -> BytesIO:
    """Render components as a high-quality PNG image (synchronous version).

    Args:
        components (Sequence[Component]): The components to render.
        theme: The theme to use ('light' or 'dark'). Defaults to 'dark'.

    Returns:
        BytesIO: The image data as bytes.
    """
    options = {
        "format": "png",
        "quality": "100",  # Maximum quality
        "quiet": "",
        "width": "1200",  # Fixed width for consistency
    }

    # Render high-quality PNG image of HTML to BytesIO
    html_content = render_components_html(components, theme=theme)
    # Use False to get bytes directly from imgkit
    img_bytes = imgkit.from_string(html_content, False, options=options)
    # Create BytesIO object from the returned bytes
    output = BytesIO(img_bytes)
    output.seek(0)
    return output


async def render_components_image_async(
    components: Sequence[Component],
    theme: str = "dark",
    executor: Optional[ThreadPoolExecutor] = None,
) -> BytesIO:
    """Render components as a high-quality PNG image (asynchronous version).

    This function runs the imgkit conversion in a thread pool to avoid blocking
    the event loop, since imgkit spawns an external wkhtmltoimage process.

    Args:
        components (Sequence[Component]): The components to render.
        theme: The theme to use ('light' or 'dark'). Defaults to 'dark'.
        executor: Optional ThreadPoolExecutor to use. If None, creates a temporary one.

    Returns:
        BytesIO: The image data as bytes.
    """
    loop = asyncio.get_event_loop()

    if executor is None:
        # Create a temporary executor for this call
        with ThreadPoolExecutor(max_workers=1) as temp_executor:
            return await loop.run_in_executor(
                temp_executor, render_components_image, components, theme
            )
    else:
        # Use the provided executor
        return await loop.run_in_executor(
            executor, render_components_image, components, theme
        )


def render_components_md(
    components: Sequence[Component],
    slack_format: bool = False,
    discord_format: bool = False,
) -> str:
    """Compile components to Markdown.

    Args:
        components (Sequence[Component]): The components to include in the Markdown.
        slack_format (bool): Render the components using Slack's subset of Markdown features.
        discord_format (bool): Render the components using Discord's markdown features.

    Returns:
        str: The generated Markdown.
    """
    components = _components_list(components)
    return "\n\n".join(
        [
            c.md(slack_format=slack_format, discord_format=discord_format)
            for c in components
        ]
    ).strip()


def _components_list(components: Sequence[Component]) -> ListType[Component]:
    if components is None:
        return []
    if isinstance(components, (Component, str)):
        components = [components]
    return [Text(comp) if isinstance(comp, str) else comp for comp in components]
