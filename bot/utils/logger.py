import logging
import logging.handlers
from pathlib import Path


def setup_logging(log_level: str = "INFO") -> None:
    """Configure root logger with file rotation + stdout."""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "bot.log",
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(log_level.upper())
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(stream_handler)
