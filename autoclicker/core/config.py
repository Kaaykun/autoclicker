"""Configuration dataclasses and their JSON representation.

Implemented in M1. See PLAN.md sections 4.1-4.3 for the field-level spec.

Planned types:
    IntervalConfig  -- hours/minutes/seconds/millis plus jitter settings
    ClickConfig     -- button, click type, inter-click gap, hold duration
    RepeatConfig    -- fixed count or until-stopped
    TargetConfig    -- follow-cursor | fixed point | sequence, with the points
    SafetyConfig    -- countdown, corner failsafe, panic behaviour
    Profile         -- the above plus a name and schema_version
"""

from __future__ import annotations

SCHEMA_VERSION = 1
