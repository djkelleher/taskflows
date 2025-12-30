"""Environments page for managing named environments."""
from dominate import document
from dominate import tags as e
from dominate.util import raw

from ui.common import Page
from ui.components.sidebar_layout import sidebar_layout, NavLink, BreadcrumbItem
from taskflows.ui.components.environment_form import environment_form
from taskflows.ui.components.shared import shared


def create_environments_page(mode: str = "list", env_name: str = None) -> Page:
    """Create environments page.

    Args:
        mode: 'list' to show all environments, 'create' for new form, 'edit' for edit form
        env_name: Environment name when mode='edit'
    """
    if mode == "create":
        title = "Create Environment"
        page_file = "environments_create"
    elif mode == "edit":
        title = f"Edit Environment - {env_name}"
        page_file = f"environments_edit_{env_name}"
    else:
        title = "Environments"
        page_file = "environments"

    doc = document(title=f"Taskflows - {title}")

    # Add CSS link
    with doc.head:
        e.link(rel="stylesheet", href="/static/main.css")

    # Create sidebar layout
    nav_items = [
        NavLink(label="Dashboard", href="/", icon="home"),
        NavLink(label="Logs", href="/logs", icon="docs"),
        NavLink(label="Environments", href="/environments", icon="projects", active=True),
        NavLink(label="Logout", href="#", icon="account"),
    ]

    breadcrumbs = [
        BreadcrumbItem(label="Environments", is_current=(mode == "list"))
    ]
    if mode in ("create", "edit"):
        breadcrumbs.append(BreadcrumbItem(label=title, is_current=True))

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
        if mode == "list":
            # List mode - show all environments
            with e.div(_class="mb-6 flex justify-between items-center"):
                with e.div():
                    e.h1("Named Environments", _class="text-3xl font-bold text-gray-800")
                    e.p(
                        "Manage reusable environment configurations",
                        _class="text-gray-600 mt-2",
                    )
                e.a(
                    "+ Create Environment",
                    href="/environments/create",
                    _class="btn btn-primary",
                )

            # Environments table
            with e.div(_class="overflow-x-auto"):
                with e.table(
                    id="environments-table",
                    _class="min-w-full bg-white border border-gray-300 rounded-lg overflow-hidden",
                ):
                    with e.thead(_class="bg-gray-100 border-b border-gray-300"):
                        with e.tr():
                            e.th(
                                "Name",
                                _class="px-4 py-3 text-left text-xs font-medium text-gray-700 uppercase tracking-wider",
                            )
                            e.th(
                                "Type",
                                _class="px-4 py-3 text-left text-xs font-medium text-gray-700 uppercase tracking-wider",
                            )
                            e.th(
                                "Description",
                                _class="px-4 py-3 text-left text-xs font-medium text-gray-700 uppercase tracking-wider",
                            )
                            e.th(
                                "Created",
                                _class="px-4 py-3 text-left text-xs font-medium text-gray-700 uppercase tracking-wider",
                            )
                            e.th(
                                "Actions",
                                _class="px-4 py-3 text-left text-xs font-medium text-gray-700 uppercase tracking-wider",
                            )

                    e.tbody(id="environments-tbody", _class="divide-y divide-gray-200")

            # JavaScript for loading and managing environments
            raw("""
<script>
document.addEventListener('DOMContentLoaded', () => {
    loadEnvironments();
});

async function loadEnvironments() {
    try {
        const token = localStorage.getItem('access_token');
        const res = await fetch('/api/environments', {
            headers: {'Authorization': 'Bearer ' + token}
        });

        if (!res.ok) throw new Error('Failed to load environments');

        const environments = await res.json();
        renderEnvironments(environments);
    } catch (err) {
        console.error('Error loading environments:', err);
        showError('Failed to load environments');
    }
}

function renderEnvironments(environments) {
    const tbody = document.getElementById('environments-tbody');
    tbody.innerHTML = '';

    if (environments.length === 0) {
        const tr = document.createElement('tr');
        const td = document.createElement('td');
        td.colSpan = 5;
        td.className = 'px-4 py-8 text-center text-gray-500';
        td.textContent = 'No environments found. Create one to get started.';
        tr.appendChild(td);
        tbody.appendChild(tr);
        return;
    }

    environments.forEach(env => {
        const tr = document.createElement('tr');
        tr.className = 'hover:bg-gray-50';

        // Name
        const tdName = document.createElement('td');
        tdName.className = 'px-4 py-3 text-sm font-medium text-gray-900';
        tdName.textContent = env.name;
        tr.appendChild(tdName);

        // Type
        const tdType = document.createElement('td');
        tdType.className = 'px-4 py-3 text-sm';
        const typeBadge = document.createElement('span');
        typeBadge.className = 'px-2 py-1 rounded-full text-xs font-semibold';
        if (env.type === 'venv') {
            typeBadge.classList.add('bg-blue-100', 'text-blue-700');
            typeBadge.textContent = 'Venv';
        } else {
            typeBadge.classList.add('bg-purple-100', 'text-purple-700');
            typeBadge.textContent = 'Docker';
        }
        tdType.appendChild(typeBadge);
        tr.appendChild(tdType);

        // Description
        const tdDesc = document.createElement('td');
        tdDesc.className = 'px-4 py-3 text-sm text-gray-700';
        tdDesc.textContent = env.description || '-';
        tr.appendChild(tdDesc);

        // Created
        const tdCreated = document.createElement('td');
        tdCreated.className = 'px-4 py-3 text-sm text-gray-700';
        tdCreated.textContent = new Date(env.created_at).toLocaleDateString();
        tr.appendChild(tdCreated);

        // Actions
        const tdActions = document.createElement('td');
        tdActions.className = 'px-4 py-3 text-sm space-x-2';

        const editBtn = document.createElement('a');
        editBtn.href = `/environments/edit?name=${encodeURIComponent(env.name)}`;
        editBtn.textContent = 'Edit';
        editBtn.className = 'btn btn-primary text-xs px-3 py-1';
        tdActions.appendChild(editBtn);

        const deleteBtn = document.createElement('button');
        deleteBtn.textContent = 'Delete';
        deleteBtn.className = 'btn btn-danger text-xs px-3 py-1';
        deleteBtn.onclick = () => deleteEnvironment(env.name);
        tdActions.appendChild(deleteBtn);

        tr.appendChild(tdActions);

        tbody.appendChild(tr);
    });
}

async function deleteEnvironment(name) {
    const confirmed = await confirm(
        `Are you sure you want to delete environment "${name}"?`,
        'Delete',
        'Cancel'
    );
    if (!confirmed) return;

    try {
        const token = localStorage.getItem('access_token');
        const res = await fetch(`/api/environments/${encodeURIComponent(name)}`, {
            method: 'DELETE',
            headers: {'Authorization': 'Bearer ' + token}
        });

        if (!res.ok) {
            const error = await res.json();
            throw new Error(error.detail || 'Failed to delete environment');
        }

        showSuccess('Environment deleted successfully');
        loadEnvironments();
    } catch (err) {
        console.error('Error deleting environment:', err);
        showError('Failed to delete environment: ' + err.message);
    }
}
</script>
""")

        else:
            # Create/Edit mode - show form
            with e.div(_class="mb-6"):
                e.h1(title, _class="text-3xl font-bold text-gray-800")
                e.p(
                    "Configure environment settings" if mode == "create" else "Update environment configuration",
                    _class="text-gray-600 mt-2",
                )

            environment_form()

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
    if mode in ("create", "edit"):
        js_files.update(environment_form.js_files)

    return Page(html=doc, file_name=page_file, js_files=js_files)
