import importlib.util
import sys

from . import alerts as _alerts
from . import components as _components
from . import discord as _discord
from . import slack as _slack
from .alerts import (
    MsgDst as MsgDst,
    PeriodicMsgs as PeriodicMsgs,
    PeriodicMsgSender as PeriodicMsgSender,
    get_alerts_log as get_alerts_log,
    send_alert as send_alert,
)
from .components import *  # noqa: F403
from .discord import (
    DiscordChannel as DiscordChannel,
    discord_settings as discord_settings,
    send_discord_message as send_discord_message,
)
from .emails import (
    EmailAddrs as EmailAddrs,
    email_settings as email_settings,
    send_email as send_email,
)
from .report import Report as Report
from .slack import (
    SlackChannel as SlackChannel,
    send_slack_message as send_slack_message,
    slack_settings as slack_settings,
)
from .utils import (
    Emoji as Emoji,
    EmojiCycle as EmojiCycle,
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
