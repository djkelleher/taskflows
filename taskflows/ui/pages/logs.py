"""Logs page for viewing service logs."""
from dominate import document
from dominate import tags as e
from dominate.util import raw

from ui.common import Page
from ui.components.sidebar_layout import sidebar_layout, NavLink, BreadcrumbItem
from taskflows.ui.components.log_viewer import log_viewer
from taskflows.ui.components.shared import shared


def create_logs_page(service_name: str) -> Page:
    """Create logs page for a specific service."""
    doc = document(title=f"Taskflows - Logs - {service_name}")

    # Add CSS link
    with doc.head:
        e.link(rel="stylesheet", href="/static/main.css")

    # Create sidebar layout
    nav_items = [
        NavLink(label="Dashboard", href="/", icon="home"),
        NavLink(label="Logs", href="/logs", icon="docs", active=True),
        NavLink(label="Environments", href="/environments", icon="projects"),
        NavLink(label="Logout", href="#", icon="account"),
    ]

    breadcrumbs = [
        BreadcrumbItem(label="Dashboard"),
        BreadcrumbItem(label="Logs"),
        BreadcrumbItem(label=service_name, is_current=True),
    ]

    taskflows_logo = """<span class="text-2xl font-bold text-white">Taskflows</span>"""

    layout = sidebar_layout(
        nav_items=nav_items,
        breadcrumbs=breadcrumbs,
        logo_svg=taskflows_logo,
        logo_href="/",
        logo_label="Taskflows",
        sidebar_bg_class="bg-electric-blue",
    )

    # Add content to the layout's content area
    with layout.content_area:
        # Page header
        with e.div(_class="mb-6 flex justify-between items-center"):
            with e.div():
                e.h1(f"Logs: {service_name}", _class="text-3xl font-bold text-gray-800")
                e.p(
                    "View and search service logs",
                    _class="text-gray-600 mt-2",
                )
            e.a(
                "Back to Dashboard",
                href="/",
                _class="btn btn-secondary",
            )

        # Log viewer
        log_viewer(service_name=service_name)

    doc.body.add(layout)

    # Add logout handler
    raw(
        """
<script>
document.addEventListener('DOMContentLoaded', () => {
    // Handle logout
    const logoutLink = document.querySelector('a[href="#"]');
    if (logoutLink && logoutLink.textContent.includes('Logout')) {
        logoutLink.addEventListener('click', (e) => {
            e.preventDefault();
            localStorage.removeItem('access_token');
            localStorage.removeItem('refresh_token');
            window.location.href = '/login';
        });
    }

    // Check if user is authenticated
    const token = localStorage.getItem('access_token');
    if (!token) {
        window.location.href = '/login';
    }
});
</script>
"""
    )

    # Collect JS files from components
    js_files = set()
    js_files.update(shared.js_files)  # Add shared utilities first
    js_files.update(log_viewer.js_files)

    return Page(html=doc, file_name=f"logs_{service_name}", js_files=js_files)
