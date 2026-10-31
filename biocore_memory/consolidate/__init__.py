# OWNER: engine-core
# -*- coding: utf-8 -*-
"""Consolidation mechanisms (default OFF, pure functions, no engine wiring)."""
from .gated import should_consolidate
from .tree import build_summary
from .reflection import propose
from .neighbors import strengthen
from .writeback import apply_neighbors, apply_reflections, write_tree

__all__ = ["should_consolidate", "build_summary", "propose", "strengthen",
           "apply_reflections", "apply_neighbors", "write_tree"]
