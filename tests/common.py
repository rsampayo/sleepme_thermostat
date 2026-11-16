"""Test helpers shared across HA releases.

HA 2026.11 ships its own pytest plugin, pytest-homeassistant. Older releases
use pytest-homeassistant-custom-component, which provides the same helpers
under a different module name.
"""

try:
    from pytest_homeassistant.common import MockConfigEntry
except ImportError:
    from pytest_homeassistant_custom_component.common import MockConfigEntry

__all__ = ["MockConfigEntry"]
