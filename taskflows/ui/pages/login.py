"""Login page for taskflows web UI."""
from dominate import document
from dominate import tags as e
from dominate.util import raw

from ui.common import Page


def create_login_page() -> Page:
    """Create the login page with username/password authentication."""
    doc = document(title="Taskflows Login")

    # Add CSS link
    with doc.head:
        e.link(rel="stylesheet", href="/static/main.css")

    with doc.body:
        with e.div(_class="min-h-screen flex items-center justify-center bg-gray-100"):
            with e.div(_class="max-w-md w-full bg-white rounded-lg shadow-md p-8"):
                # Logo/Title
                e.h2(
                    "Taskflows",
                    _class="text-3xl font-bold text-center mb-2 text-electric-blue",
                )
                e.p(
                    "Service Management Dashboard",
                    _class="text-center text-gray-600 mb-6",
                )

                # Error message (hidden by default)
                e.div(
                    id="error-msg",
                    _class="hidden mb-4 p-3 bg-red-100 border border-red-400 text-red-700 rounded-lg text-sm",
                )

                # Login form
                with e.form(id="login-form", _class="space-y-4"):
                    # Username field
                    with e.div():
                        e.label(
                            "Username",
                            _for="username",
                            _class="block text-sm font-medium mb-2 text-gray-700",
                        )
                        e.input_(
                            type="text",
                            id="username",
                            name="username",
                            _class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-electric-blue",
                            required=True,
                            autofocus=True,
                        )

                    # Password field
                    with e.div():
                        e.label(
                            "Password",
                            _for="password",
                            _class="block text-sm font-medium mb-2 text-gray-700",
                        )
                        e.input_(
                            type="password",
                            id="password",
                            name="password",
                            _class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-electric-blue",
                            required=True,
                        )

                    # Submit button
                    e.button(
                        "Login",
                        type="submit",
                        id="login-btn",
                        _class="w-full btn btn-primary",
                    )

        # Login JavaScript
        raw(
            """
<script>
// Check if already logged in
const token = localStorage.getItem('access_token');
if (token) {
    // Verify token is valid by trying to access a protected endpoint
    fetch('/api/services?as_json=true', {
        headers: {'Authorization': 'Bearer ' + token}
    }).then(res => {
        if (res.ok) {
            window.location.href = '/';
        }
    });
}

document.getElementById('login-form').addEventListener('submit', async (e) => {
    e.preventDefault();

    const loginBtn = document.getElementById('login-btn');
    const errorMsg = document.getElementById('error-msg');
    const username = document.getElementById('username').value;
    const password = document.getElementById('password').value;

    // Disable button and show loading state
    loginBtn.disabled = true;
    loginBtn.textContent = 'Logging in...';
    errorMsg.classList.add('hidden');

    try {
        const res = await fetch('/auth/login', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({username, password})
        });

        if (res.ok) {
            const data = await res.json();
            localStorage.setItem('access_token', data.access_token);
            localStorage.setItem('refresh_token', data.refresh_token);
            window.location.href = '/';
        } else {
            const data = await res.json().catch(() => ({detail: 'Invalid credentials'}));
            errorMsg.textContent = data.detail || 'Invalid credentials';
            errorMsg.classList.remove('hidden');
            loginBtn.disabled = false;
            loginBtn.textContent = 'Login';
        }
    } catch (err) {
        console.error('Login error:', err);
        errorMsg.textContent = 'Login failed. Please try again.';
        errorMsg.classList.remove('hidden');
        loginBtn.disabled = false;
        loginBtn.textContent = 'Login';
    }
});
</script>
"""
        )

    return Page(html=doc, file_name="login")
