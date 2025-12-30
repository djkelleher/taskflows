"""Shared utilities component for Taskflows UI.

This component provides common JavaScript utilities used across all components:
- Authentication (token refresh, auth headers)
- Toast notifications
- Debouncing
- Confirmation dialogs
- Fetch with retry
"""
from pathlib import Path

from ui.components.component import component

here = Path(__file__).parent


class shared(component):
    """Shared utilities that are included in all pages."""

    js_files = {here / "shared.js"}

    def __init__(self, **kwargs):
        # This is a utility component that doesn't render any HTML
        # It only provides JavaScript functionality
        super().__init__("script", **kwargs)
        # Empty script tag - the JS file will be included separately
        self.attributes['type'] = 'module'
