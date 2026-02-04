<h2 align="center" style="color: #B4EC51;">dl-alerts</h2>

[![Tests](https://github.com/DankLabDev/dl-alerts/workflows/Tests/badge.svg)](https://github.com/DankLabDev/dl-alerts/actions?query=workflow%3ATests)

## Installation

### Prerequisites
```bash
# Install system dependencies (required for imgkit functionality)
sudo apt install wkhtmltopdf fonts-noto-color-emoji
```

2. **Install the package**:
```bash
pip install dl-alerts
```

### Alternative: Direct Installation
If you have access to the CodeArtifact repository URL and token:
```bash
pip install dl-alerts --index-url https://aws:YOUR_TOKEN@YOUR_REPOSITORY_URL/
```

### Development Installation
For development or if you need the latest version:
```bash
git clone https://github.com/dan-kelleher/dl-alerts.git
cd dl-alerts
pip install -e .
```

## What is here?
- Simple components for constructing rich messages and alerts. Components and get rendered into markdown, html, or images for Slack, Discord, Email.
- Utilities for sending messages to Slack, Discord, Email.

## Components

| Component Class | Description |
|-----------------|-------------|
| [Text](./alerts/components.py#L115) | A component that displays formatted text. |
| [Map](./alerts/components.py#L179) | A component that displays formatted key/value pairs. |
| [Table](./alerts/components.py#L234) | A component that displays tabular data. |
| [List](./alerts/components.py#L357) | A component that displays a list of text strings as bullet points. |
| [Link](./alerts/components.py#L397) | A component that displays clickable links. |
| [Image](./alerts/components.py#L431) | A component that displays images. |
| [Card](./alerts/components.py#L480) | A container component with header, body, and optional footer. |
| [Timeline](./alerts/components.py#L565) | A component that displays chronological events. |
| [Badge](./alerts/components.py#L642) | A component that displays small labels for status or categories. |
| [PriceChange](./alerts/components.py#L684) | A component that displays price movements with appropriate colors. |
| [StatusIndicator](./alerts/components.py#L737) | A component that displays status with colored indicators. |
| [Grid](./alerts/components.py#L804) | A component that arranges other components in a grid layout. |
| [LineBreak](./alerts/components.py#L869) | A line beak (to be inserted between components). |
| [ProgressBar](./alerts/components.py#L891) | A progress bar component for showing completion percentages. |
| [Alert](./alerts/components.py#L951) | An alert/notification component for important messages. |
| [Quote](./alerts/components.py#L1012) | A quote/blockquote component for highlighted text. |
| [CodeBlock](./alerts/components.py#L1067) | A code block component for displaying code snippets. |
| [MetricCard](./alerts/components.py#L1119) | A metric card component for displaying key performance indicators. |
| [Divider](./alerts/components.py#L1212) | A divider component for separating content. |
| [Breadcrumb](./alerts/components.py#L1267) | A breadcrumb navigation component. |
| [Avatar](./alerts/components.py#L1301) | An avatar/profile image component. |
| [EmptyState](./alerts/components.py#L1364) | A component for displaying empty state messages. |
| [LoadingSpinner](./alerts/components.py#L1420) | A loading spinner component for indicating progress. |

### Examples

Here are examples of how to use each component with their various arguments:

#### Text Component
```python
from alerts.components import Text, ContentType, FontSize

# Basic text
text = Text(value="Hello World")

# Important text with large font
important_text = Text(value="Critical Alert", level=ContentType.IMPORTANT, font_size=FontSize.LARGE)

# Warning text with small font
warning_text = Text(value="System Warning", level=ContentType.WARNING, font_size=FontSize.SMALL)

# Error text with medium font
error_text = Text(value="Database Connection Failed", level=ContentType.ERROR, font_size=FontSize.MEDIUM)
```

#### Map Component
```python
from alerts.components import Map

# Regular key-value display
data_map = Map(data={
    "CPU Usage": "85%",
    "Memory": "12.5 GB",
    "Disk Space": "45% free"
})

# Inline key-value display
inline_map = Map(
    data={
        "Status": "Online",
        "Version": "2.1.0",
        "Uptime": "15 days"
    },
    inline=True
)
```

#### Table Component
```python
from alerts.components import Table

# Basic table
table = Table(rows=[
    {"Name": "John Doe", "Age": "30", "Department": "Engineering"},
    {"Name": "Jane Smith", "Age": "28", "Department": "Marketing"},
    {"Name": "Bob Johnson", "Age": "35", "Department": "Sales"}
])

# Table with title and custom columns
table_with_title = Table(
    rows=[
        {"Product": "Widget A", "Price": "$10.99", "Stock": "150"},
        {"Product": "Widget B", "Price": "$24.99", "Stock": "75"}
    ],
    title="Inventory Status",
    columns=["Product", "Price", "Stock"]
)
```

#### List Component
```python
from alerts.components import List

# Unordered list
todo_list = List(items=[
    "Review pull requests",
    "Update documentation",
    "Deploy to staging"
])

# Ordered list
steps_list = List(
    items=[
        "Install dependencies",
        "Run tests",
        "Build application",
        "Deploy to production"
    ],
    ordered=True
)
```

#### Link Component
```python
from alerts.components import Link

# Basic link
link = Link(url="https://example.com", text="Visit Example")

# Button-style link
button_link = Link(
    url="https://dashboard.example.com",
    text="Open Dashboard",
    button_style=True
)
```

#### Image Component
```python
from alerts.components import Image

# Basic image
image = Image(src="https://example.com/chart.png", alt="Sales Chart")

# Image with custom dimensions
chart_image = Image(
    src="https://example.com/analytics.png",
    alt="Analytics Dashboard",
    width=800,
    height=600
)
```

#### Card Component
```python
from alerts.components import Card, Text, Badge

# Card with header, body, and footer
card = Card(
    body=[
        Text(value="This is the main content of the card"),
        Badge(text="Active", color="#059669", background_color="#D1FAE5")
    ],
    header="System Status",
    footer="Last updated: 2 minutes ago",
    border_color="#2563EB"
)
```

#### Timeline Component
```python
from alerts.components import Timeline

# Timeline of events
timeline = Timeline(events=[
    {
        "time": "09:00 AM",
        "title": "System Startup",
        "description": "All services started successfully"
    },
    {
        "time": "10:30 AM",
        "title": "Database Backup",
        "description": "Daily backup completed"
    },
    {
        "time": "12:00 PM",
        "title": "User Activity Peak",
        "description": "High traffic detected"
    }
])
```

#### Badge Component
```python
from alerts.components import Badge

# Default badge
status_badge = Badge(text="Active")

# Custom colored badge
error_badge = Badge(text="Error", color="#DC2626", background_color="#FEE2E2")

# Success badge
success_badge = Badge(text="Completed", color="#059669", background_color="#D1FAE5")
```

#### PriceChange Component
```python
from alerts.components import PriceChange

# Price increase
price_up = PriceChange(current=150.25, previous=140.00, currency="$", show_percentage=True)

# Price decrease without percentage
price_down = PriceChange(current=95.50, previous=100.00, currency="€", show_percentage=False)

# Price change with different currency
crypto_change = PriceChange(current=45000, previous=42000, currency="₿", show_percentage=True)
```

#### StatusIndicator Component
```python
from alerts.components import StatusIndicator

# Green status with icon
online_status = StatusIndicator(status="Online", color="green", show_icon=True)

# Red status without icon
error_status = StatusIndicator(status="Error", color="red", show_icon=False)

# Yellow warning status
warning_status = StatusIndicator(status="Warning", color="yellow", show_icon=True)
```

#### Grid Component
```python
from alerts.components import Grid, Text, Badge

# 2x2 grid layout
grid = Grid(
    components=[
        [Text(value="Top Left"), Text(value="Top Right")],
        [Badge(text="Active"), Text(value="Bottom Right")]
    ],
    gap=20
)
```

#### LineBreak Component
```python
from alerts.components import LineBreak

# Single line break
single_break = LineBreak(n_break=1)

# Multiple line breaks
multiple_breaks = LineBreak(n_break=3)
```

#### ProgressBar Component
```python
from alerts.components import ProgressBar

# Basic progress bar
progress = ProgressBar(value=75, max_value=100, color="blue", show_percentage=True, width=400)

# Custom colored progress bar without percentage
custom_progress = ProgressBar(value=60, max_value=80, color="green", show_percentage=False, width=300)
```

#### Alert Component
```python
from alerts.components import Alert

# Info alert
info_alert = Alert(message="System maintenance scheduled for tonight", alert_type="info")

# Error alert with title
error_alert = Alert(
    message="Database connection failed",
    alert_type="error",
    title="Connection Error"
)

# Success alert
success_alert = Alert(message="Data backup completed successfully", alert_type="success")
```

#### Quote Component
```python
from alerts.components import Quote

# Basic quote
quote = Quote(text="The best way to predict the future is to invent it.")

# Quote with author
quote_with_author = Quote(
    text="Simplicity is the ultimate sophistication.",
    author="Leonardo da Vinci"
)

# Quote with author and source
full_quote = Quote(
    text="Stay hungry, stay foolish.",
    author="Steve Jobs",
    source="Stanford Commencement Speech"
)
```

#### CodeBlock Component
```python
from alerts.components import CodeBlock

# Basic code block
code = CodeBlock(code="print('Hello, World!')", language="python")

# Code block with line numbers
numbered_code = CodeBlock(
    code="""def fibonacci(n):
    if n <= 1:
        return n
    return fibonacci(n-1) + fibonacci(n-2)""",
    language="python",
    show_line_numbers=True
)
```

#### MetricCard Component
```python
from alerts.components import MetricCard

# Basic metric card
metric = MetricCard(title="Revenue", value="$125,000")

# Metric card with change and trend
metric_with_change = MetricCard(
    title="Monthly Active Users",
    value="45,230",
    change="+12.5%",
    trend="up",
    period="vs last month"
)
```

#### Divider Component
```python
from alerts.components import Divider

# Simple divider
divider = Divider()

# Divider with text
section_divider = Divider(text="Section Break", style="dashed")

# Dotted divider
dotted_divider = Divider(text="End of Report", style="dotted")
```

#### Breadcrumb Component
```python
from alerts.components import Breadcrumb

# Navigation breadcrumbs
breadcrumb = Breadcrumb(items=[
    "Home",
    "Dashboard",
    "Analytics",
    "Reports"
])
```

#### Avatar Component
```python
from alerts.components import Avatar

# Avatar with image
avatar_with_image = Avatar(
    name="John Doe",
    image_url="https://example.com/avatar.jpg",
    size="large"
)

# Avatar with initials only
avatar_initials = Avatar(name="Jane Smith", size="medium")

# Small avatar
small_avatar = Avatar(name="Bob Johnson", size="small")
```

#### EmptyState Component
```python
from alerts.components import EmptyState

# Basic empty state
empty_state = EmptyState(
    icon="📊",
    title="No Data Available",
    description="There are no records to display at this time."
)

# Empty state with action
empty_with_action = EmptyState(
    icon="🔍",
    title="No Search Results",
    description="Try adjusting your search criteria.",
    action_text="Clear Filters"
)
```

#### LoadingSpinner Component
```python
from alerts.components import LoadingSpinner

# Default loading spinner
spinner = LoadingSpinner()

# Custom loading text
custom_spinner = LoadingSpinner(text="Processing data...", size="large")

# Small spinner
small_spinner = LoadingSpinner(text="Loading...", size="small")
```

## Sending Messages

The `AlertLogger` class provides a convenient way to send messages to regular logging and simultaneously Slack or Discord channels with automatic message buffering and periodic sending.

### Basic AlertLogger Usage

```python
import asyncio
from alerts import AlertLogger, SlackChannel, DiscordChannel, EmailAddrs

# Create an AlertLogger for Slack
slack_logger = await AlertLogger.create(
    channel=SlackChannel(channel="#alerts"),
    msg_max_freq=5,  # Buffer messages for 5 seconds before sending
    disable_messages=False
)

# Send different types of messages
slack_logger.info(msg="System is running normally")
slack_logger.warning(msg="High memory usage detected")
slack_logger.error(msg="Database connection failed")

# Create an AlertLogger for Discord
discord_logger = await AlertLogger.create(
    channel="https://discord.com/api/webhooks/your-webhook-url",
    msg_max_freq=2
)

# Send immediate message (bypass buffering)
discord_logger.info(msg="Urgent update", nowait=True)

# Create an AlertLogger for Email
email_config = EmailAddrs(
    sender_addr="alerts@company.com",
    receiver_addr=["admin@company.com", "ops@company.com"],
    smtp_server="smtp.gmail.com",
    smtp_port=587,
    password="your-app-password"
)

email_logger = await AlertLogger.create(
    channel=email_config,
    msg_max_freq=60  # Buffer for 1 minute before sending
)

# Send messages to email
email_logger.info(msg="Daily backup completed")
email_logger.warning(msg="Disk space running low")
```

### Direct Sending Functions

For immediate sending without buffering, you can use the direct sending functions:

#### send_alert - Send to one or more sestinations

```python
import asyncio
from alerts import (
    send_alert, send_slack_message, SlackChannel, DiscordChannel, EmailAddrs,
    Text, Table, Badge, ContentType, FontSize
)

# Create message components
components = [
    Text(value="🚨 Critical System Alert", level=ContentType.ERROR, font_size=FontSize.LARGE),
    Table(
        rows=[
            {"Service": "Database", "Status": "Down", "Impact": "High"},
            {"Service": "API Gateway", "Status": "Degraded", "Impact": "Medium"},
            {"Service": "Cache", "Status": "Healthy", "Impact": "None"}
        ],
        title="Service Status"
    ),
    Badge(text="URGENT", color="#DC2626", background_color="#FEE2E2")
]

# Send to multiple destinations.
destinations = [
    SlackChannel(channel="#alerts"),
    DiscordChannel(webhook_url="https://discord.com/api/webhooks/your-webhook-url"),
    EmailAddrs(
        sender_addr="alerts@company.com",
        receiver_addr=["admin@company.com"],
        smtp_server="smtp.gmail.com",
        smtp_port=587,
        password="your-app-password"
    )
]

success = await send_alert(content=components, send_to=destinations)

# Send to Slack channel
success = await send_slack_message(
    channel=SlackChannel(channel="#daily-reports"),
    content=components,
    subject="Daily System Report",
    attachment_files=["/path/to/report.pdf", "/path/to/data.csv"],
    zip_attachment_files=True,  # Zip multiple files together
    retries=3
)

# Send email
success = await send_email(
    content=components,
    send_to=EmailAddrs(
        sender_addr="reports@company.com",
        receiver_addr=["manager@company.com", "analyst@company.com"],
        smtp_server="smtp.gmail.com",
        smtp_port=587,
        password="your-app-password"
    ),
    subject="Monthly Performance Report - January 2024",
    retries=2
)
```

## Alert Destinations

### Slack Alerts Configuration

To use Slack as an alert destination, you'll need to set up a Slack App:

1. Go to [Slack Apps](https://api.slack.com/apps?new_app=1) and click **Create New App** → **From Scratch**
   - Give it a name and select your workspace
2. Navigate to the **OAuth & Permissions** on the left sidebar
3. Scroll down to the **Bot Token Scopes** section and add these OAuth scopes:
   - `chat:write` - To post messages in channels
   - `file:write` - To upload files/attachments
4. Scroll up and click **Install App to Workspace**
5. Copy the **Bot User OAuth Token** (starts with `xoxb-`)
6. In Slack, go to your channel and add the app:
   - Click the channel name → **Integrations** → **Add apps** → select your app

### Discord Configuration
To use Discord as an alert destination, you'll need to set up a Discord webhook:

1. Go to your Discord server settings
2. Navigate to **Integrations** → **Webhooks**
3. Click **New Webhook**
4. Choose the channel where you want to send messages
5. Copy the webhook URL (it should look like `https://discord.com/api/webhooks/...`)

You can optionally set environment variables:
- `DISCORD_WEBHOOK_URL` - Default webhook URL to use
- `DISCORD_ATTACHMENT_MAX_SIZE_MB` - Maximum attachment size (default: 8MB)
- `DISCORD_INLINE_TABLES_MAX_ROWS` - Max rows for inline tables (default: 50)

### Email Configuration
To use email, you'll need:

- An email address to send from
- The password for that email account
- SMTP server details (defaults to Gmail's)

If using Gmail, you may need to:
1. Enable 2-factor authentication
2. Create an ["App Password"](https://security.google.com/settings/security/apppasswords) to use instead of your regular password


## TODO
function with zip logic - accachment max size
automatic Map inlining based on text lengths.
check for rich features we can use: https://github.com/Textualize/rich/tree/master/docs, https://rich.readthedocs.io/en/stable/reference.html
check docs, type annotation, comments
run tests
test actual outputs: slack, discord,
