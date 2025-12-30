"""Service table component with multi-select and filtering."""
from pathlib import Path

from dominate import tags as e
from dominate.util import raw

from ui.components.component import component

here = Path(__file__).parent


class service_table(component):
    """Interactive service table with multi-select, search, and real-time updates."""

    js_files = {here / "service_table.js"}

    def __init__(self, **kwargs):
        super().__init__("div", _class="w-full", **kwargs)

        with self:
            # Search and batch actions toolbar
            with e.div(_class="mb-4 flex gap-4 items-center"):
                # Search input
                e.input_(
                    type="text",
                    id="service-search",
                    placeholder="Search services...",
                    _class="flex-1 px-4 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-electric-blue",
                )

                # Batch action buttons (disabled by default)
                with e.div(id="batch-actions", _class="flex gap-2"):
                    e.button(
                        "Start Selected",
                        id="batch-start",
                        _class="btn btn-success",
                        disabled=True,
                        onclick="batchAction('start')",
                    )
                    e.button(
                        "Stop Selected",
                        id="batch-stop",
                        _class="btn btn-danger",
                        disabled=True,
                        onclick="batchAction('stop')",
                    )
                    e.button(
                        "Restart Selected",
                        id="batch-restart",
                        _class="btn btn-primary",
                        disabled=True,
                        onclick="batchAction('restart')",
                    )

            # Services table
            with e.div(_class="overflow-x-auto"):
                with e.table(
                    id="services-table",
                    _class="min-w-full bg-white border border-gray-300 rounded-lg overflow-hidden",
                ):
                    # Table header
                    with e.thead(_class="bg-gray-100 border-b border-gray-300"):
                        with e.tr():
                            e.th(
                                e.input_(
                                    type="checkbox",
                                    id="select-all",
                                    _class="rounded",
                                    onchange="toggleSelectAll(this)",
                                ),
                                _class="px-4 py-3 text-left text-xs font-medium text-gray-700 uppercase tracking-wider",
                            )
                            e.th(
                                "Service",
                                _class="px-4 py-3 text-left text-xs font-medium text-gray-700 uppercase tracking-wider",
                            )
                            e.th(
                                "Status",
                                _class="px-4 py-3 text-left text-xs font-medium text-gray-700 uppercase tracking-wider",
                            )
                            e.th(
                                "Schedule",
                                _class="px-4 py-3 text-left text-xs font-medium text-gray-700 uppercase tracking-wider",
                            )
                            e.th(
                                "Last Run",
                                _class="px-4 py-3 text-left text-xs font-medium text-gray-700 uppercase tracking-wider",
                            )
                            e.th(
                                "Actions",
                                _class="px-4 py-3 text-left text-xs font-medium text-gray-700 uppercase tracking-wider",
                            )

                    # Table body (populated by JavaScript)
                    e.tbody(id="services-tbody", _class="divide-y divide-gray-200")

            # Loading indicator
            with e.div(
                id="loading-indicator",
                _class="hidden text-center py-4 text-gray-500",
            ):
                raw(
                    """
<svg class="inline animate-spin h-5 w-5 mr-2" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
</svg>
Loading services...
"""
                )
