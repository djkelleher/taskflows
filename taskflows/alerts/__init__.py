import importlib.util
import sys

from . import alerts as _alerts
from . import components as _components
from . import discord as _discord
from . import slack as _slack
from .alerts import (
    MsgDst as MsgDst,
)
from .alerts import (
    PeriodicMsgs as PeriodicMsgs,
)
from .alerts import (
    PeriodicMsgSender as PeriodicMsgSender,
)
from .alerts import (
    get_alerts_log as get_alerts_log,
)
from .alerts import (
    send_alert as send_alert,
)
from .components import *  # noqa: F403
from .discord import (
    DiscordChannel as DiscordChannel,
)
from .discord import (
    discord_settings as discord_settings,
)
from .discord import (
    send_discord_message as send_discord_message,
)
from .emails import (
    EmailAddrs as EmailAddrs,
)
from .emails import (
    email_settings as email_settings,
)
from .emails import (
    send_email as send_email,
)
from .report import Report as Report
from .slack import (
    SlackChannel as SlackChannel,
)
from .slack import (
    send_slack_message as send_slack_message,
)
from .slack import (
    slack_settings as slack_settings,
)
from .utils import (
    Emoji as Emoji,
)
from .utils import (
    EmojiCycle as EmojiCycle,
)
from .utils import (
    price_dir_emoji as price_dir_emoji,
)

if importlib.util.find_spec("alerts") is None:
    # Backward-compatible import path for older dl-alerts users. Do not
    # shadow a separately installed top-level alerts package.
    sys.modules.setdefault("alerts", sys.modules[__name__])
    sys.modules.setdefault("alerts.alerts", _alerts)
    sys.modules.setdefault("alerts.components", _components)
    sys.modules.setdefault("alerts.discord", _discord)
    sys.modules.setdefault("alerts.slack", _slack)

# Task-level alert configuration and best-effort event senders.
from .task_config import (
    Alerts as Alerts,
)
from .task_config import (
    normalize_alerts as normalize_alerts,
)
from .task_config import (
    send_error_alert as send_error_alert,
)
from .task_config import (
    send_finish_alert as send_finish_alert,
)
from .task_config import (
    send_start_alert as send_start_alert,
)
