# -*- coding: utf-8 -*-
"""BioCore runtime package: host-neutral policy shared by every adapter."""
from __future__ import annotations

__version__ = "0.1.0"
VERSION = (0, 1, 0)

from . import pipeline

__all__ = ["pipeline"]
