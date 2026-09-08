"""Permission detection, and a shortcut to the pane that fixes it.

macOS needs two separate grants and gives no useful error when they are
missing -- the app simply does nothing, which is the worst possible failure
mode. These checks turn that silence into a sentence.

Both checks go through ctypes rather than pyobjc so they add no dependency:
``AXIsProcessTrusted`` for Accessibility, ``IOHIDCheckAccess`` for Input
Monitoring.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

_ACCESSIBILITY_PANE = (
    "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
)
_INPUT_MONITORING_PANE = (
    "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent"
)

#: IOHIDCheckAccess request type for "I want to observe events".
_HID_REQUEST_LISTEN = 1
_HID_GRANTED = 0


class Permission(str, Enum):
    ACCESSIBILITY = "accessibility"
    INPUT_MONITORING = "input_monitoring"


class PermissionState(str, Enum):
    GRANTED = "granted"
    DENIED = "denied"
    UNKNOWN = "unknown"
    NOT_REQUIRED = "not_required"


@dataclass(frozen=True)
class PermissionReport:
    accessibility: PermissionState
    input_monitoring: PermissionState

    @property
    def all_clear(self) -> bool:
        return all(
            state in (PermissionState.GRANTED, PermissionState.NOT_REQUIRED)
            for state in (self.accessibility, self.input_monitoring)
        )

    def summary(self) -> str:
        if self.all_clear:
            return "All required permissions are granted."
        missing = []
        if self.accessibility is not PermissionState.GRANTED:
            missing.append("Accessibility (needed to send clicks)")
        if self.input_monitoring is not PermissionState.GRANTED:
            missing.append("Input Monitoring (needed for global hotkeys)")
        return "Missing permission: " + "; ".join(missing)


def is_macos() -> bool:
    return sys.platform == "darwin"


def is_windows() -> bool:
    return sys.platform.startswith("win")


def check_permissions() -> PermissionReport:
    """Report on the grants this platform needs. Never raises."""
    if not is_macos():
        return PermissionReport(PermissionState.NOT_REQUIRED, PermissionState.NOT_REQUIRED)
    return PermissionReport(_check_accessibility(), _check_input_monitoring())


def _check_accessibility() -> PermissionState:
    try:
        path = ctypes.util.find_library("ApplicationServices")
        if not path:
            return PermissionState.UNKNOWN
        lib = ctypes.cdll.LoadLibrary(path)
        lib.AXIsProcessTrusted.restype = ctypes.c_bool
        lib.AXIsProcessTrusted.argtypes = []
        return PermissionState.GRANTED if lib.AXIsProcessTrusted() else PermissionState.DENIED
    except Exception:  # pragma: no cover - macOS only
        logger.debug("Accessibility check failed", exc_info=True)
        return PermissionState.UNKNOWN


def _check_input_monitoring() -> PermissionState:
    try:
        path = ctypes.util.find_library("IOKit")
        if not path:
            return PermissionState.UNKNOWN
        lib = ctypes.cdll.LoadLibrary(path)
        # IOHIDCheckAccess is macOS 10.15+; on anything older the symbol is
        # absent and the permission does not exist either.
        if not hasattr(lib, "IOHIDCheckAccess"):
            return PermissionState.NOT_REQUIRED
        lib.IOHIDCheckAccess.restype = ctypes.c_int
        lib.IOHIDCheckAccess.argtypes = [ctypes.c_uint32]
        result = lib.IOHIDCheckAccess(_HID_REQUEST_LISTEN)
        if result == _HID_GRANTED:
            return PermissionState.GRANTED
        return PermissionState.DENIED if result == 1 else PermissionState.UNKNOWN
    except Exception:  # pragma: no cover - macOS only
        logger.debug("Input Monitoring check failed", exc_info=True)
        return PermissionState.UNKNOWN


def open_privacy_settings(permission: Permission) -> bool:
    """Open the System Settings pane for a permission. False if we could not."""
    if not is_macos():
        return False
    url = (
        _ACCESSIBILITY_PANE
        if permission is Permission.ACCESSIBILITY
        else _INPUT_MONITORING_PANE
    )
    try:
        subprocess.run(["open", url], check=True, timeout=10)
    except Exception:  # pragma: no cover - macOS only
        logger.warning("Could not open the privacy settings pane", exc_info=True)
        return False
    return True


def permission_guidance() -> str:
    """A short, plain explanation of what to grant and to what."""
    if is_windows():
        return (
            "Windows needs no special permission for normal use. One exception: "
            "a normal process cannot send clicks to a window running as "
            "administrator -- to click into an elevated app, run this one as "
            "administrator too."
        )
    if not is_macos():
        return "No special permissions are needed on this platform."
    return (
        "macOS needs two permissions, granted to whichever app hosts this "
        "process -- your terminal while running from source, or Autoclicker.app "
        "once bundled:\n\n"
        "  - Accessibility, to send clicks\n"
        "  - Input Monitoring, for global hotkeys\n\n"
        "Both live in System Settings > Privacy & Security. After granting "
        "either one you must quit and reopen the host app before it takes "
        "effect."
    )
