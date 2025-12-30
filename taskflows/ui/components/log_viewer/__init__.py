"""Log viewer component for displaying service logs."""
from pathlib import Path

from dominate import tags as e
from dominate.util import raw

from ui.components.component import component

here = Path(__file__).parent


class log_viewer(component):
    """Interactive log viewer with search and auto-scroll."""

    js_files = {here / "log_viewer.js"}

    def __init__(self, service_name: str, **kwargs):
        super().__init__("div", _class="w-full", **kwargs)

        self.service_name = service_name

        with self:
            # Controls bar
            with e.div(_class="mb-4 flex gap-4 items-center justify-between"):
                # Left controls
                with e.div(_class="flex gap-4 items-center"):
                    # Max lines selector
                    with e.div(_class="flex items-center gap-2"):
                        e.label(
                            "Lines:",
                            _for="log-lines",
                            _class="text-sm font-medium text-gray-700",
                        )
                        with e.select(
                            id="log-lines",
                            _class="px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-electric-blue",
                            onchange="updateLogLines(this.value)",
                        ):
                            e.option("100", value="100")
                            e.option("500", value="500")
                            e.option("1000", value="1000", selected=True)
                            e.option("5000", value="5000")

                    # Auto-scroll toggle
                    with e.div(_class="flex items-center gap-2"):
                        e.input_(
                            type="checkbox",
                            id="auto-scroll",
                            _class="rounded",
                            checked=True,
                            onchange="toggleAutoScroll(this.checked)",
                        )
                        e.label(
                            "Auto-scroll",
                            _for="auto-scroll",
                            _class="text-sm font-medium text-gray-700",
                        )

                # Right controls
                with e.div(_class="flex gap-2"):
                    e.button(
                        "Refresh",
                        _class="btn btn-primary",
                        onclick="loadLogs()",
                    )
                    e.button(
                        "Download",
                        _class="btn btn-secondary",
                        onclick="downloadLogs()",
                    )

            # Search bar
            e.input_(
                type="text",
                id="log-search",
                placeholder="Search logs...",
                _class="w-full px-4 py-2 mb-4 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-electric-blue",
                oninput="searchLogs(this.value)",
            )

            # Log container
            with e.div(
                _class="bg-gray-900 rounded-lg p-4 overflow-auto font-mono text-sm",
                style="max-height: 600px;",
                id="log-container",
            ):
                e.pre(
                    id="log-content",
                    _class="text-green-400 whitespace-pre-wrap",
                )

            # Hidden input to store service name for JavaScript
            e.input_(
                type="hidden",
                id="service-name",
                value=service_name,
            )
