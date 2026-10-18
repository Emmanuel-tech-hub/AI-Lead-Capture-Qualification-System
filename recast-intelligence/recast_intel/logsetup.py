import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(root: Path, verbose: bool = False) -> None:
    logs = root / "logs"
    logs.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s level=%(levelname)s module=%(name)s %(message)s")
    file_handler = RotatingFileHandler(logs / "recast.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(fmt)
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    console.setLevel(logging.INFO if verbose else logging.WARNING)
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers[:] = [file_handler, console]
    for noisy in ("httpx", "httpcore", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
