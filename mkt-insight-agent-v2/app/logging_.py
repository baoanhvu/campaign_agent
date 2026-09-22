"""Structured logging setup."""
from __future__ import annotations

import logging
import sys


def setup_logging(level: str = "info") -> logging.Logger:
    numeric = getattr(logging, level.upper(), logging.INFO)
    root = logging.getLogger("mkt")
    if root.handlers:
        return root
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            '{"ts":"%(asctime)s","lvl":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    root.addHandler(handler)
    root.setLevel(numeric)
    logging.getLogger("uvicorn").setLevel(numeric)
    return root


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"mkt.{name}")
