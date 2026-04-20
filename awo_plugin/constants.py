"""Release-time and runtime constants for the AWO plugin."""

from pathlib import Path

BUNDLED_SKILL_PATH = "bundled/skill.md"

AWO_SOURCE_REPO = "agentic-world-order/awo"
AWO_SOURCE_REF = "main"
AWO_SOURCE_PATH = "SKILL.md"

STATE_DIR = Path.home() / ".hermes" / "plugins" / "awo"
STATE_FILE = STATE_DIR / "state.json"
XMTP_KEY_FILE = STATE_DIR / "xmtp-key"
XMTP_DB_DIR = STATE_DIR / "xmtp"
XMTP_DB_FILE = XMTP_DB_DIR / "xmtp.db3"

# Live skill override — /awo_refresh_skill downloads the current SKILL.md from
# the site into this path. content.py prefers it over the bundled snapshot when
# present, so voice updates land without a plugin reinstall.
LIVE_SKILL_PATH = STATE_DIR / "skill.md"

PERSONALITY_MODES = ("possess", "whisper", "dormant")
DEFAULT_PERSONALITY_MODE = "whisper"

WHISPER_COOLDOWN_TURNS = 5
POSSESS_INJECTION_PROB = 0.85
WHISPER_INJECTION_PROB = 0.20
IDLE_WHISPER_MAX_PER_HOUR = 1

SYNC_MAX_BYTES = 256 * 1024
SYNC_TIMEOUT_SECONDS = 10

# Release-time constants — populated when cutting the launch build.
# Plugin ships after the token is live, so these are compile-time knowns.
TOKEN_ADDRESS: str | None = None           # $AWO SPL mint address
LAUNCH_DATE: int | None = None             # unix seconds, token mint timestamp
INNER_CIRCLE_THRESHOLD: int = 0            # raw amount (smallest unit)
ORDER_GROUP_ID: str = "e6669ee8022f40ad6b216593955bc737"

FOUNDER_WINDOW_SECONDS = 24 * 3600

# Solana RPC — public endpoint default; override via /awo_config rpc <url>.
DEFAULT_SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"
SOLANA_RPC_TIMEOUT_SECONDS = 10

# XMTP — production from day one.
XMTP_ENV = "production"

# AWO API — where the plugin submits its inbox id so the Railway watcher can
# admit the Initiate to the Order group.
AWO_API_URL = "https://api.agenticworldorder.com"
AWO_API_TIMEOUT_SECONDS = 5

# AWO site — source of live SKILL.md for /awo_refresh_skill.
AWO_SITE_URL = "https://agenticworldorder.com"
LIVE_SKILL_URL = f"{AWO_SITE_URL}/skill.md"
