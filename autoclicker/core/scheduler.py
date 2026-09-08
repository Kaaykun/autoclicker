"""Drift-free interval scheduling and jitter.

Absolute monotonic deadlines rather than cumulative sleeps, plus a short spin
at the tail for sub-millisecond accuracy. Implemented in M1; see PLAN.md
section 3 (Timing).
"""

from __future__ import annotations
