"""Simplified UI build script that avoids problematic imports."""
import os
import subprocess
from pathlib import Path

# Set environment variables before any taskflows imports
os.environ['TASKFLOWS_DATA_DIR'] = '/tmp/taskflows_data'
os.environ['TASKFLOWS_FILE_DIR'] = '/tmp/taskflows_logs'

# Create pages and write HTML manually
from taskflows.ui.pages.login import create_login_page
from taskflows.ui.pages.dashboard import create_dashboard_page
from taskflows.ui.pages.environments import create_environments_page

# Output directory
# Script is now in taskflows/ui/
UI_DIR = Path(__file__).parent
OUTPUT_DIR = UI_DIR / "static"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

print("Building Taskflows UI (simplified)...")

# Create pages
pages = [
    create_login_page(),
    create_dashboard_page(),
    create_environments_page(mode="list"),
    create_environments_page(mode="create"),
]

# Collect all JS files from pages
all_js_files = set()
for page in pages:
    all_js_files.update(page.js_files)

# Write HTML files
for page in pages:
    # Add CSS and JS links to head
    from dominate import tags as e
    with page.html.head:
        e.link(rel="stylesheet", href="/static/main.css")
        e.script(src="/static/main.js")
        # Add Preline JS at end
        e.script(src="https://cdn.jsdelivr.net/npm/preline@2.0.3/dist/preline.min.js")

    # Write HTML file
    file_name = page.file_name if page.file_name.endswith(".html") else f"{page.file_name}.html"
    file_path = OUTPUT_DIR / file_name
    print(f"Writing {file_path}...")
    file_path.write_text(page.html.render())

# Compile JavaScript
print("Compiling JavaScript...")
js_content = []
for js_file in all_js_files:
    if Path(js_file).exists():
        js_content.append(Path(js_file).read_text())

js_file_path = OUTPUT_DIR / "main.js"
js_file_path.write_text("\n\n".join(js_content))
print(f"Wrote {js_file_path}")

# Compile Tailwind CSS
print("Compiling Tailwind CSS...")
input_css = Path(__file__).parent / "input.css"
output_css = OUTPUT_DIR / "main.css"

cmd = [
    "npx",
    "tailwindcss",
    "-i", str(input_css),
    "-o", str(output_css),
    "--minify",
]

try:
    result = subprocess.run(
        cmd,
        cwd=Path(__file__).parent,
        capture_output=True,
        text=True,
        check=True,
    )
    print(f"Tailwind CSS compiled successfully to {output_css}")
except subprocess.CalledProcessError as e:
    print(f"Tailwind CSS compilation failed: {e.stderr}")
    exit(1)

print(f"\n✅ UI compiled successfully to {OUTPUT_DIR}")
print(f"   - HTML files: {len(list(OUTPUT_DIR.glob('*.html')))}")
print(f"   - JavaScript: {OUTPUT_DIR / 'main.js'}")
print(f"   - CSS: {OUTPUT_DIR / 'main.css'}")
