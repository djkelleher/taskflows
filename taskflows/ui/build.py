"""Build script for compiling the Taskflows UI.

This script compiles all pages and components into static HTML, CSS, and JavaScript files.
"""
import logging
from pathlib import Path

from ui.compiler.core import compile_pages

from taskflows.ui.pages.login import create_login_page
from taskflows.ui.pages.dashboard import create_dashboard_page
from taskflows.ui.pages.environments import create_environments_page
import taskflows.ui.components

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Paths
UI_DIR = Path(__file__).parent
OUTPUT_DIR = UI_DIR / "static"
TASKFLOWS_ROOT = UI_DIR.parent.parent


def build_ui():
    """Compile all UI pages and assets."""
    logger.info("Building Taskflows UI...")

    # Create all pages
    pages = [
        create_login_page(),
        create_dashboard_page(),
        create_environments_page(mode="list"),
        create_environments_page(mode="create"),
        # Edit page will be generated dynamically at runtime
    ]

    logger.info(f"Compiling {len(pages)} pages...")

    # Compile pages with taskflows components
    compile_pages(
        to_compile=pages,
        output_dir=OUTPUT_DIR,
        output_js_file="main.js",
        output_css_file="main.css",
        custom_components=[taskflows.ui.components],
        pretty=True,
    )

    logger.info(f"✅ UI compiled successfully to {OUTPUT_DIR}")
    logger.info(f"   - HTML files: {len(list(OUTPUT_DIR.glob('*.html')))}")
    logger.info(f"   - JavaScript: {OUTPUT_DIR / 'main.js'}")
    logger.info(f"   - CSS: {OUTPUT_DIR / 'main.css'}")


if __name__ == "__main__":
    build_ui()
