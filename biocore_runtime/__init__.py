# -*- coding: utf-8 -*-
"""BioCore core runtime (host-neutral).

The core has its own version, independent from any host adapter or plugin
package version.
"""
__version__ = "0.1.0"
VERSION = tuple(int(part) for part in __version__.split("."))

# -*- coding: utf-8 -*-
"""BioCore runtime package: host-neutral policy shared by every adapter."""
from __future__ import annotations

from . import pipeline

__all__ = ["pipeline"]
