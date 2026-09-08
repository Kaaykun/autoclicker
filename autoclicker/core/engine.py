"""The click loop.

Runs on its own thread, driven by a ``threading.Event`` so a stop is immediate
even mid-interval. Emits progress via callbacks the UI layer adapts to Qt
signals. Implemented in M1.
"""

from __future__ import annotations
