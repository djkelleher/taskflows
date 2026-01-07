#!/usr/bin/env python3
"""
Example script demonstrating all alert-msgs components and how to send them
to Slack, Discord, or email.

Usage:
    python send_all_components_example.py --platform slack --channel "#general"
    python send_all_components_example.py --platform discord --webhook "https://discord.com/api/webhooks/..."
    python send_all_components_example.py --platform email --to "user@example.com"
"""

import argparse
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

from alerts.components import (
    Alert,
    Badge,
    Breadcrumb,
    Card,
    CodeBlock,
    Component,
    ContentType,
    Divider,
    FontSize,
    Grid,
    Image,
    JSONComponent,
    LineBreak,
)
from alerts.components import List as ListComponent
from alerts.components import (
    LogEntry,
    Map,
    MetricCard,
    PriceChange,
    ProgressBar,
    SpinnerComponent,
    StatusIndicator,
    Table,
    Text,
    Timeline,
    TreeView,
)
from alerts.discord import DiscordChannel, send_discord_message
from alerts.emails import EmailAddrs, send_email
from alerts.slack import SlackChannel, send_slack_message


def create_all_components() -> List[Component]:
    """Create a list containing examples of all available components."""
    components = []

    # Title
    components.append(
        Text(
            "🎨 Alert Messages Component Gallery", ContentType.IMPORTANT, FontSize.LARGE
        )
    )
    components.append(
        Text(
            "Demonstrating all available components", ContentType.INFO, FontSize.MEDIUM
        )
    )
    components.append(Divider())

    # Text Components
    components.append(Text("Text Components", ContentType.IMPORTANT, FontSize.LARGE))
    components.append(
        Text("Regular text with INFO level", ContentType.INFO, FontSize.MEDIUM)
    )
    components.append(
        Text("Warning text example", ContentType.WARNING, FontSize.MEDIUM)
    )
    components.append(Text("Error text example", ContentType.ERROR, FontSize.MEDIUM))
    components.append(
        Text("Important text example", ContentType.IMPORTANT, FontSize.MEDIUM)
    )
    components.append(Text("Small font size", ContentType.INFO, FontSize.SMALL))
    components.append(Text("Large font size", ContentType.INFO, FontSize.LARGE))
    components.append(LineBreak())

    # Map Component
    components.append(Text("Map Component", ContentType.IMPORTANT, FontSize.LARGE))
    components.append(
        Map(
            {
                "Server": "production-01",
                "Status": "Running",
                "CPU": "45%",
                "Memory": "2.3 GB",
                "Uptime": "15 days",
            }
        )
    )
    components.append(LineBreak())

    # Table Component
    components.append(Text("Table Component", ContentType.IMPORTANT, FontSize.LARGE))
    components.append(
        Table(
            headers=["Name", "Department", "Salary", "Status"],
            rows=[
                ["Alice Johnson", "Engineering", "$120,000", "Active"],
                ["Bob Smith", "Marketing", "$85,000", "Active"],
                ["Charlie Brown", "Sales", "$95,000", "On Leave"],
                ["Diana Prince", "HR", "$90,000", "Active"],
            ],
        )
    )
    components.append(LineBreak())

    # List Component
    components.append(Text("List Component", ContentType.IMPORTANT, FontSize.LARGE))
    components.append(
        ListComponent(
            [
                "First item in the list",
                "Second item with more details",
                "Third item - important note",
                "Fourth item to demonstrate",
                "Fifth and final item",
            ]
        )
    )
    components.append(LineBreak())

    # Alert Component
    components.append(Text("Alert Component", ContentType.IMPORTANT, FontSize.LARGE))
    components.append(
        Alert(
            "⚠️ System maintenance scheduled for tonight at 11 PM EST",
            ContentType.WARNING,
        )
    )
    components.append(Alert("✅ Deployment completed successfully", ContentType.INFO))
    components.append(
        Alert("❌ Critical error in payment processing", ContentType.ERROR)
    )
    components.append(LineBreak())

    # Badge Component
    components.append(Text("Badge Component", ContentType.IMPORTANT, FontSize.LARGE))
    components.append(Badge("NEW", "green"))
    components.append(Badge("BETA", "blue"))
    components.append(Badge("DEPRECATED", "red"))
    components.append(Badge("EXPERIMENTAL", "yellow"))
    components.append(LineBreak())

    # Status Indicator Component
    components.append(
        Text("Status Indicator Component", ContentType.IMPORTANT, FontSize.LARGE)
    )
    components.append(StatusIndicator("Database", "online"))
    components.append(StatusIndicator("API Gateway", "degraded"))
    components.append(StatusIndicator("Message Queue", "offline"))
    components.append(LineBreak())

    # Progress Bar Component
    components.append(
        Text("Progress Bar Component", ContentType.IMPORTANT, FontSize.LARGE)
    )
    components.append(ProgressBar(75, "Data Processing"))
    components.append(ProgressBar(30, "Upload Progress"))
    components.append(ProgressBar(100, "Task Completed"))
    components.append(LineBreak())

    # Code Block Component
    components.append(
        Text("Code Block Component", ContentType.IMPORTANT, FontSize.LARGE)
    )
    components.append(
        CodeBlock(
            """
def fibonacci(n):
    if n <= 1:
        return n
    return fibonacci(n-1) + fibonacci(n-2)

# Example usage
result = fibonacci(10)
print(f"Fibonacci(10) = {result}")
""",
            language="python",
        )
    )
    components.append(LineBreak())

    # Price Change Component
    components.append(
        Text("Price Change Component", ContentType.IMPORTANT, FontSize.LARGE)
    )
    components.append(PriceChange("AAPL", 150.25, 145.30))
    components.append(PriceChange("GOOGL", 2850.00, 2875.50))
    components.append(PriceChange("TSLA", 750.00, 750.00))
    components.append(LineBreak())

    # Metric Card Component
    components.append(
        Text("Metric Card Component", ContentType.IMPORTANT, FontSize.LARGE)
    )
    components.append(MetricCard("Revenue", "$1.2M", "+15%", "green"))
    components.append(MetricCard("Active Users", "45,230", "-3%", "red"))
    components.append(MetricCard("Response Time", "125ms", "0%", "blue"))
    components.append(LineBreak())

    # Timeline Component
    components.append(Text("Timeline Component", ContentType.IMPORTANT, FontSize.LARGE))
    now = datetime.now()
    components.append(
        Timeline(
            [
                (now - timedelta(hours=3), "System started"),
                (now - timedelta(hours=2), "Configuration loaded"),
                (now - timedelta(hours=1), "Services initialized"),
                (now - timedelta(minutes=30), "Health check passed"),
                (now, "Ready for operations"),
            ]
        )
    )
    components.append(LineBreak())

    # Breadcrumb Component
    components.append(
        Text("Breadcrumb Component", ContentType.IMPORTANT, FontSize.LARGE)
    )
    components.append(
        Breadcrumb(["Home", "Products", "Electronics", "Laptops", "Gaming"])
    )
    components.append(LineBreak())

    # Card Component
    components.append(Text("Card Component", ContentType.IMPORTANT, FontSize.LARGE))
    components.append(
        Card(
            title="Feature Release",
            content="We're excited to announce the release of our new dashboard with real-time analytics and improved performance.",
            footer="Released on " + datetime.now().strftime("%Y-%m-%d"),
        )
    )
    components.append(LineBreak())

    # Grid Component
    components.append(Text("Grid Component", ContentType.IMPORTANT, FontSize.LARGE))
    grid_items = [
        Text("Grid Item 1", ContentType.INFO, FontSize.SMALL),
        Text("Grid Item 2", ContentType.WARNING, FontSize.SMALL),
        Text("Grid Item 3", ContentType.ERROR, FontSize.SMALL),
        Text("Grid Item 4", ContentType.IMPORTANT, FontSize.SMALL),
    ]
    components.append(Grid(grid_items, columns=2))
    components.append(LineBreak())

    # JSON Component
    components.append(Text("JSON Component", ContentType.IMPORTANT, FontSize.LARGE))
    components.append(
        JSONComponent(
            {
                "user": {
                    "id": 12345,
                    "name": "John Doe",
                    "email": "john@example.com",
                    "roles": ["admin", "developer"],
                    "settings": {
                        "theme": "dark",
                        "notifications": True,
                        "language": "en",
                    },
                }
            }
        )
    )
    components.append(LineBreak())

    # Tree View Component
    components.append(
        Text("Tree View Component", ContentType.IMPORTANT, FontSize.LARGE)
    )
    tree_structure = {
        "root": {
            "folder1": {
                "file1.txt": None,
                "file2.txt": None,
                "subfolder": {"file3.txt": None},
            },
            "folder2": {"file4.txt": None},
        }
    }
    components.append(TreeView(tree_structure))
    components.append(LineBreak())

    # Log Entry Component
    components.append(
        Text("Log Entry Component", ContentType.IMPORTANT, FontSize.LARGE)
    )
    components.append(
        LogEntry(datetime.now(), "INFO", "Application started successfully")
    )
    components.append(LogEntry(datetime.now(), "WARNING", "Memory usage above 80%"))
    components.append(
        LogEntry(datetime.now(), "ERROR", "Failed to connect to database")
    )
    components.append(LineBreak())

    # Spinner Component (Note: won't animate in static messages)
    components.append(Text("Spinner Component", ContentType.IMPORTANT, FontSize.LARGE))
    components.append(SpinnerComponent("Loading data..."))
    components.append(LineBreak())

    # Live Data Component
    components.append(
        Text("Live Data Component", ContentType.IMPORTANT, FontSize.LARGE)
    )
    components.append(LineBreak())

    # Image Component (using a placeholder URL)
    components.append(Text("Image Component", ContentType.IMPORTANT, FontSize.LARGE))
    components.append(
        Image(
            url="https://via.placeholder.com/400x200.png?text=Sample+Image",
            alt_text="Sample placeholder image",
            width=400,
            height=200,
        )
    )

    # Footer
    components.append(Divider())
    components.append(
        Text(
            f"Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            ContentType.INFO,
            FontSize.SMALL,
        )
    )

    return components


async def send_to_slack(channel: str):
    """Send all components to a Slack channel."""
    components = create_all_components()
    slack_channel = SlackChannel(channel)

    try:
        await send_slack_message(
            content=components, channel=slack_channel, username="Component Gallery Bot"
        )
        print(f"✅ Successfully sent to Slack channel: {channel}")
    except Exception as e:
        print(f"❌ Failed to send to Slack: {e}")


async def send_to_discord(webhook_url: str):
    """Send all components to a Discord channel via webhook."""
    components = create_all_components()
    discord_channel = DiscordChannel(webhook_url)

    try:
        await send_discord_message(
            content=components,
            channel=discord_channel,
            username="Component Gallery Bot",
        )
        print(f"✅ Successfully sent to Discord")
    except Exception as e:
        print(f"❌ Failed to send to Discord: {e}")


async def send_to_email(
    to_address: str,
    from_address: str,
    password: str,
    smtp_server: str = "smtp.gmail.com",
):
    """Send all components via email."""
    components = create_all_components()

    email_config = EmailAddrs(
        sender_addr=from_address,
        password=password,
        receiver_addr=to_address,
        smtp_server=smtp_server,
        smtp_port=465,
    )

    try:
        await send_email(
            content=components,
            send_to=email_config,
            subject="Alert Messages - Component Gallery",
        )
        print(f"✅ Successfully sent email to: {to_address}")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Send all alert-msgs components to various platforms"
    )
    parser.add_argument(
        "--platform",
        choices=["slack", "discord", "email"],
        required=True,
        help="Platform to send the message to",
    )

    # Slack arguments
    parser.add_argument(
        "--channel", help="Slack channel (e.g., '#general' or '@username')"
    )

    # Discord arguments
    parser.add_argument("--webhook", help="Discord webhook URL")

    # Email arguments
    parser.add_argument("--to", help="Email recipient address")
    parser.add_argument("--from", dest="from_addr", help="Email sender address")
    parser.add_argument("--password", help="Email password")
    parser.add_argument(
        "--smtp", default="smtp.gmail.com", help="SMTP server (default: smtp.gmail.com)"
    )

    args = parser.parse_args()

    # Create async event loop
    loop = asyncio.get_event_loop()

    try:
        if args.platform == "slack":
            if not args.channel:
                print("❌ Error: --channel is required for Slack")
                return
            loop.run_until_complete(send_to_slack(args.channel))

        elif args.platform == "discord":
            if not args.webhook:
                print("❌ Error: --webhook is required for Discord")
                return
            loop.run_until_complete(send_to_discord(args.webhook))

        elif args.platform == "email":
            if not all([args.to, args.from_addr, args.password]):
                print("❌ Error: --to, --from, and --password are required for email")
                return
            loop.run_until_complete(
                send_to_email(args.to, args.from_addr, args.password, args.smtp)
            )
    finally:
        loop.close()


if __name__ == "__main__":
    main()
