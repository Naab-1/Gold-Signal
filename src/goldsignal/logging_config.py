"""Structured logging setup.

Called once at process startup. Downstream modules should log *why* a
signal or candle batch was accepted or rejected via the standard `logging`
module — never via print(). No secrets are logged; once API keys exist
(Phase 3+), they must never be interpolated into log messages.
"""

from __future__ import annotations

import logging
import time

_FORMAT = "%(asctime)s.%(msecs)03dZ %(levelname)s %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%dT%H:%M:%S"


def configure_logging(level: str = "INFO") -> None:
    logging.Formatter.converter = time.gmtime  # timestamps in UTC
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=_FORMAT,
        datefmt=_DATEFMT,
        force=True,
    )
