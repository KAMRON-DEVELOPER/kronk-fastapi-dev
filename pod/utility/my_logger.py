import sys
from pathlib import Path

from loguru import logger as my_logger


def custom_log_sink(message):
    """Custom Loguru Sink - Extracts Stack Trace and Formats Logs."""
    # ANSI color codes for console
    reset = "\033[0m"
    red = "\033[31m"
    green = "\033[32m"
    yellow = "\033[33m"
    blue = "\033[34m"
    magenta = "\033[35m"
    cyan = "\033[36m"
    white = "\033[37m"

    # Log level mapping with colors and emojis
    log_levels = {
        "TRACE": {"emoji": "🔍", "color": cyan},
        "DEBUG": {"emoji": "🐛", "color": blue},
        "INFO": {"emoji": "💡", "color": green},
        "WARNING": {"emoji": "🚨", "color": yellow},
        "ERROR": {"emoji": "🌋", "color": red},
        "CRITICAL": {"emoji": "👾", "color": magenta},
    }

    record = message.record
    message = record.get("message")
    full_path = Path(__file__).parent.parent.parent
    relative_path = Path(record.get("file").path).relative_to(full_path)

    # Extract log level information
    level = record["level"].name
    color = log_levels.get(level, {}).get("color", white)
    emoji = log_levels.get(level, {}).get("emoji", "📌")

    # Print to standard output
    sys.stdout.write(f"{color}({relative_path})    {emoji} {message}{reset}\n")


my_logger.remove()
my_logger.add(custom_log_sink, level="TRACE")
