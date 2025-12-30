"""Dashboard page for taskflows web UI."""
from dominate import document
from dominate import tags as e
from dominate.util import raw

from ui.common import Page
from ui.components.sidebar_layout import sidebar_layout, NavLink, BreadcrumbItem, ICONS
from taskflows.ui.components.service_table import service_table
from taskflows.ui.components.shared import shared


def create_dashboard_page() -> Page:
    """Create the main dashboard page with service management."""
    doc = document(title="Taskflows - Dashboard")

    # Add CSS link
    with doc.head:
        e.link(rel="stylesheet", href="/static/main.css")

    # Create sidebar layout
    nav_items = [
        NavLink(label="Dashboard", href="/", icon="home", active=True),
        NavLink(label="Logs", href="/logs", icon="docs"),
        NavLink(label="Environments", href="/environments", icon="projects"),
        NavLink(label="Logout", href="#", icon="account"),
    ]

    breadcrumbs = [
        BreadcrumbItem(label="Dashboard", is_current=True)
    ]

    # Custom logo SVG for taskflows
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
        with e.div(_class="mb-6"):
            e.h1("Service Management", _class="text-3xl font-bold text-gray-800")
            e.p(
                "Manage and monitor your taskflows services",
                _class="text-gray-600 mt-2",
            )

        # Service table
        service_table()

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
    js_files.update(service_table.js_files)

    return Page(html=doc, file_name="index", js_files=js_files)
