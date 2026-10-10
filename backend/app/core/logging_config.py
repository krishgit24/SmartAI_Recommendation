"""Basic operational logging. Never log full account numbers - use core.security.mask()."""
from __future__ import annotations

import logging


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(level=level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # httpx logs full request URLs, which can contain account numbers.
    logging.getLogger("httpx").setLevel(logging.WARNING)
