# Phase 6 — Post-v4.0.0 Follow-Up Plan

**Status:** Drafted 2026-05-18, awaiting maintainer approval. Targets `v4.1.0`.
**Companion docs:** [`AUDIT.md`](./AUDIT.md), [`ROADMAP.md`](./ROADMAP.md), [`phase-5-polish.md`](./phase-5-polish.md).
**Genesis:** five specialist agents audited the v4.0.0 release. Findings ranged from one real correctness bug (per-account rate limiter) to product polish (manifest name, README screenshots). Phase 6 is the P0 + top-half-of-P1 from that audit. Bigger feature lifts (Sleep Tracker platform, split-bed pairing, Sleep Programs blueprint) are deferred to Phase 7+.

## Goal

Close the audit's correctness gaps and ship the user-visible product polish that turns the integration's HACS card from "Thermostat" into "the SleepMe integration for HA." Concretely after Phase 6:

1. The local rate limiter is shared per-account, not per-`SleepMeAPI`-instance. Multi-device installs (N≥2) stop hammering the SleepMe API with N×budget.
2. `Retry-After` honoring is bounded — a buggy/malicious header can't park the integration for 24h.
3. The temperature slider stops "snapping back" when the next coordinator poll fails.
4. `hass.data[DOMAIN][entry.entry_id]` is replaced with `ConfigEntry.runtime_data` — closes the HA Bronze quality-scale `runtime-data` rule.
5. HACS users discover the integration by name, see screenshots, and pick a friendly device name in the config flow (not a UUID).
6. Two new sensors: continuous `water_level` percent, firmware version.
7. Dead code from 5 phases of refactor is gone.
8. Two test holes that allow a broken integration to pass are closed.

Version bump to `4.1.0`. No schema migration; `entry.data` shape is unchanged.

## Cross-cutting concern: API budget per user action

**Phase 6 strictly reduces per-account API budget consumption.** Deliverable 1 alone is the largest budget improvement since Phase 3 ripped out the verify-loop. Deliverables 2–3 bound worst-case downtime/snap-back without burning extra calls.

## Scope

| # | Source | Item | File(s) | Rough effort |
|---|---|---|---|---|
| 1 | Audit / Performance | Per-account shared rate limiter | `sleepme_api.py`, `sleepme.py` | M |
| 2 | Audit / Performance | Cap `Retry-After` at `BACKOFF_CEILING` | `sleepme_api.py` | XS |
| 3 | Audit / Performance | Optimistic window self-extend on coordinator failure | `climate.py` | XS |
| 4 | Audit / HA-core | Migrate to `ConfigEntry.runtime_data` | `__init__.py`, all platforms, `diagnostics.py` | S |
| 5 | Audit / Marketing | Rename HACS-visible name to "SleepMe (Chilipad Dock Pro)" | `manifest.json`, `hacs.json` | XS |
| 6 | Audit / Marketing | README: add 3 screenshots + Supported Devices section | `README.md`, `docs/images/` | S |
| 7 | Audit / Marketing | Device picker: show friendly name, not UUID | `config_flow.py`, `translations/*.json` | XS |
| 8 | Audit / API | `sensor.water_level` continuous percent | `sensor.py` | XS |
| 9 | Audit / API | `sensor.firmware_version` | `sensor.py` | XS |
| 10 | Audit / Code-quality | Dead code removal | `sleepme_api.py`, `const.py`, `climate.py`, `binary_sensor.py`, `sensor.py`, `sleepme.py` | XS |
| 11 | Audit / Code-quality | Kill dead `kwargs.get("temperature")` fallback | `climate.py` | XS |
| 12 | Audit / Code-quality | Strengthen 2 test holes (preset PATCH assertion, hvac PATCH assertion) | `tests/test_climate.py` | XS |
| 13 | Version | Bump `manifest.json` `version` to `4.1.0` | `manifest.json` | XS |

## Deliverables

### 1. Per-account shared rate limiter

**Files:** `custom_components/sleepme_thermostat/sleepme_api.py`, `custom_components/sleepme_thermostat/sleepme.py`.

**Today:** each `SleepMeClient` builds a fresh `SleepMeAPI` with its own deque/lock. Each config entry constructs **two** `SleepMeClient` instances (one in `__init__.py:44` directly, one inside `SleepMeUpdateManager.__init__` at `update_manager.py:43`). Result: N devices × 2 instances × 9 req/min = 18N req/min cumulative ceiling, while the server enforces per-token.

**Target:** `SleepMeAPI` caches instances on a class-level `WeakValueDictionary` keyed on `(api_url, token)`. All callers go through `SleepMeAPI.get_or_create(hass, api_url, token)`. The deque is shared across every `SleepMeClient` using the same token.

**Paste-ready patch — `sleepme_api.py`:**

```python
from weakref import WeakValueDictionary


class SleepMeAPI:
    """HTTP transport for the SleepMe developer API.

    Instances are shared per (api_url, token) so the local rate limiter caps
    cumulative load at the actual per-account ceiling, not N × ceiling for
    multi-device installs.
    """

    # Class-level cache; keyed on (api_url, token). WeakValueDictionary lets
    # GC reclaim instances after the last SleepMeClient referencing them
    # is gone (e.g. all entries unloaded).
    _instances: WeakValueDictionary[tuple[str, str], "SleepMeAPI"] = (
        WeakValueDictionary()
    )

    @classmethod
    def get_or_create(
        cls,
        hass: HomeAssistant,
        api_url: str,
        token: str,
        max_requests_per_minute: int = MAX_REQUESTS_PER_MINUTE,
    ) -> "SleepMeAPI":
        """Return the shared transport for this (api_url, token) pair."""
        key = (api_url, token)
        existing = cls._instances.get(key)
        if existing is not None:
            return existing
        new = cls(hass, api_url, token, max_requests_per_minute)
        cls._instances[key] = new
        return new

    def __init__(
        self,
        hass: HomeAssistant,
        api_url: str,
        token: str,
        max_requests_per_minute: int = MAX_REQUESTS_PER_MINUTE,
    ) -> None:
        # ... existing implementation unchanged ...
```

**Paste-ready patch — `sleepme.py`:**

```diff
 class SleepMeClient:
     def __init__(
         self, hass: HomeAssistant, api_url: str, token: str, device_id: str | None = None
     ) -> None:
         self.api_url = api_url
         self.token = token
         self.device_id = device_id
-        self.api = SleepMeAPI(hass, api_url, token)
+        self.api = SleepMeAPI.get_or_create(hass, api_url, token)
```

**Tests:** new `tests/test_sleepme_api.py::test_get_or_create_returns_same_instance`. Build two clients with identical args; assert `client_a.api is client_b.api`. Build a third client with a different token; assert `client_c.api is not client_a.api`.

**Diff shape:** `sleepme_api.py` +25 lines; `sleepme.py` 1 line changed; tests +20 lines.

**API-budget impact:** **the biggest win in Phase 6.** N=2 with 20s poll drops from worst-case 6 req/min/account (today) to bounded by the shared deque. N=3 with 10s poll stops generating server-side 429 cascades because the local limiter actually corresponds to the account-level constraint.

### 2. Cap `Retry-After` at `BACKOFF_CEILING`

**File:** `custom_components/sleepme_thermostat/sleepme_api.py`.

**Today:** `_compute_backoff` (lines 233–243) honors `Retry-After` unconditionally. `BACKOFF_CEILING = 600` only applies to the fallback computation. A bad/malicious `Retry-After: 86400` parks polling for 24h.

**Paste-ready:**

```diff
     @staticmethod
     def _compute_backoff(base: int, attempt: int, response: httpx.Response) -> float:
         """Resolve backoff seconds.

         Honors Retry-After (integer seconds or HTTP-date), capped at
         BACKOFF_CEILING to avoid being parked indefinitely by a bad header.
         Falls back to base * 2**(attempt-1), capped at BACKOFF_CEILING.
         """
         ra = response.headers.get("Retry-After")
         if ra:
+            def _cap(v: float) -> float:
+                if v > BACKOFF_CEILING:
+                    _LOGGER.warning(
+                        "Capping Retry-After %.0fs to ceiling %ds", v, BACKOFF_CEILING
+                    )
+                return min(v, float(BACKOFF_CEILING))
             try:
-                return float(int(ra))
+                return _cap(float(int(ra)))
             except ValueError:
                 try:
                     target = parsedate_to_datetime(ra).timestamp()
-                    return max(0.0, target - time.time())
+                    return _cap(max(0.0, target - time.time()))
                 except (TypeError, ValueError):
                     _LOGGER.debug("Unparsable Retry-After: %r", ra)
         return float(min(base * (2 ** (attempt - 1)), BACKOFF_CEILING))
```

**Tests:** new property test (Hypothesis): given any `Retry-After`, the returned backoff is ≤ `BACKOFF_CEILING`.

**Diff shape:** ~10 lines added.

### 3. Optimistic window self-extends on coordinator failure

**File:** `custom_components/sleepme_thermostat/climate.py`.

**Today:** `_effective_optimistic_temp` (lines 283–301) clears the optimistic value at `OPTIMISTIC_WINDOW` expiry unconditionally. If the coordinator hasn't successfully polled since the PATCH, the entity snaps back to a stale value.

**Paste-ready:**

```diff
     def _effective_optimistic_temp(self, server_value: float | None) -> float | None:
         """Return the optimistic target if it should still win, else None."""
         if self._optimistic_target_temp is None:
             return None
         now = dt_util.utcnow()
         if (
             self._optimistic_target_temp_until is not None
             and now > self._optimistic_target_temp_until
         ):
+            # If the coordinator hasn't reconciled successfully yet, keep
+            # trusting our optimistic value rather than snapping back to a
+            # stale read.
+            if not self.coordinator.last_update_success:
+                return self._optimistic_target_temp
             self._optimistic_target_temp = None
             self._optimistic_target_temp_until = None
             return None
         if server_value == self._optimistic_target_temp:
             self._optimistic_target_temp = None
             self._optimistic_target_temp_until = None
             return None
         return self._optimistic_target_temp
```

Apply the same pattern to `_effective_thermal_status`.

**Tests:** new test in `tests/test_climate.py::test_optimistic_holds_while_coordinator_fails`. Set optimistic temp; flip `coordinator.last_update_success = False`; advance time past `OPTIMISTIC_WINDOW`; assert optimistic still wins.

**Diff shape:** ~8 lines in `climate.py`; ~30 lines test.

### 4. Migrate to `ConfigEntry.runtime_data`

**Files:** `__init__.py`, `climate.py`, `binary_sensor.py`, `sensor.py`, `diagnostics.py`, plus tests that read `hass.data[DOMAIN][entry.entry_id]`.

**New types — at the top of `__init__.py`:**

```python
from dataclasses import dataclass

from homeassistant.helpers.device_registry import DeviceInfo

from .sleepme import SleepMeClient
from .update_manager import SleepMeUpdateManager


@dataclass(slots=True)
class SleepMeData:
    """Container for per-entry runtime state."""
    client: SleepMeClient
    coordinator: SleepMeUpdateManager
    device_info: DeviceInfo


type SleepMeConfigEntry = ConfigEntry[SleepMeData]
```

**`async_setup_entry` change:**

```diff
-    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
-        "client": client,
-        "coordinator": coordinator,
-        "device_info": {
-            "firmware_version": entry.data.get("firmware_version"),
-            "mac_address": entry.data.get("mac_address"),
-            "model": entry.data.get("model"),
-            "serial_number": entry.data.get("serial_number"),
-        },
-    }
+    entry.runtime_data = SleepMeData(
+        client=client,
+        coordinator=coordinator,
+        device_info={
+            "firmware_version": entry.data.get("firmware_version"),
+            "mac_address": entry.data.get("mac_address"),
+            "model": entry.data.get("model"),
+            "serial_number": entry.data.get("serial_number"),
+        },
+    )
```

`async_unload_entry` drops the `hass.data[DOMAIN].pop(entry.entry_id, None)` line entirely — HA cleans `runtime_data` automatically.

**Read-site updates** (`climate.py:74`, `sensor.py:33`, `binary_sensor.py:35`, `diagnostics.py:35`):

```diff
-    entry_data = hass.data[DOMAIN][entry.entry_id]
-    coordinator = entry_data["coordinator"]
-    device_info = build_device_info(
-        device_id, entry.title, entry_data["device_info"]
-    )
+    data = entry.runtime_data
+    coordinator = data.coordinator
+    device_info = build_device_info(device_id, entry.title, data.device_info)
```

Same pattern in `diagnostics.py` — replaces the `hass.data[DOMAIN].get(entry.entry_id, {})` defensive read with `entry.runtime_data` (which raises if accessed before setup — a real signal, not a silent `{}`).

**Tests:** update `tests/test_init.py::test_multi_entry_isolation` to check `entry.runtime_data` instead of `hass.data[DOMAIN]` keys. `tests/test_diagnostics.py::test_diagnostics_handles_missing_entry_data` becomes obsolete (the half-loaded entry case can't reach the diagnostics function anymore; HA's framework blocks it) — delete or repurpose.

**Diff shape:** `__init__.py` +15/-8; each platform 3–4 lines changed; tests 1–2 lines per file; one test deleted.

**Closes HA quality-scale `runtime-data` rule** (currently a Bronze rule we technically fail).

### 5. Rename to "SleepMe (Chilipad Dock Pro)"

**Files:** `manifest.json`, `hacs.json`.

```diff
 # manifest.json
-  "name": "SleepMe Thermostat",
+  "name": "SleepMe (Chilipad Dock Pro)",
```

```diff
 # hacs.json
-  "name": "SleepMe Thermostat"
+  "name": "SleepMe (Chilipad Dock Pro)"
```

**Risk:** HACS may treat this as a renamed integration on update. The repository URL stays the same, the integration `domain` stays `sleepme_thermostat`, so existing installs continue to work — they just see the new display name. No migration needed.

**Diff shape:** 2 lines.

### 6. README: screenshots + Supported Devices section

**Files:** `README.md`, new `docs/images/*.png`.

Add three screenshots above the Features section:
- `docs/images/hacs-card.png` — what users see in HACS search.
- `docs/images/config-flow.png` — the token entry + device picker.
- `docs/images/device-card.png` — climate entity + sensors on a HA dashboard.

Inline them with `<img src="docs/images/X.png" width="600">` (forces a reasonable size in GitHub's renderer).

Add a Supported devices section right after Features:

```markdown
## Supported devices

| Device | Status | Notes |
|---|---|---|
| Dock Pro | ✅ Tested | Maintainer runs on `Dock Pro Ramon` + `Dock Pro Chiva`. |
| Dock Pro Max | ❓ Untested | API contract appears identical; if you have one, please file an issue or PR confirming. |
| Cube Sleep System | ❓ Untested | Same SleepMe account → same API; should work but unverified. |
| OOLER | ❓ Untested | Legacy ChiliSleep device; some users on the HA forum have asked. Please file an issue if you've successfully paired one. |
| Chilipad (pre-2022) | ❌ Not supported | Original Chilipad used a different cloud API; SleepMe deprecated that flow. |
```

Add a "What's new in v4.1.0" link to the release.

**Diff shape:** ~25 lines added to README; 3 image files committed.

**Capturing the screenshots:** maintainer takes them locally after the deploy step against their HA install. Either `git add docs/images/` directly or upload to GitHub release assets and inline-link.

### 7. Device picker: friendly name, not UUID

**File:** `custom_components/sleepme_thermostat/config_flow.py`, `translations/*.json`.

**Today** — `select_device.data.device_id` label is "Device" in English and "ID del Dispositivo" in Spanish. The dropdown ITSELF correctly shows friendly names because `claimed_devices_dict = {device["id"]: device["name"] for ...}` (line 137-139) — values are names. So actually, the dropdown is already friendly; just the label needs to change.

**Verification step in PR:** confirm by reading what's currently rendered. If the label is the only issue, this is a translation-only fix:

```diff
 # en.json
       "select_device": {
         "title": "Select Dock Pro Device",
         "description": "Select the Dock Pro device you want to add.",
         "data": {
-          "device_id": "Device"
+          "device_id": "Bed / Device"
         },
         "data_description": {
-          "device_id": "Choose one of the devices discovered."
+          "device_id": "Pick the device by its name (the dropdown shows the name you set in the SleepMe app)."
         }
       }
```

If the friendly name is actually broken at the dropdown level (rendering UUIDs), the fix is in `config_flow.py:137-139` — the dict comprehension is correct as written; this might just be a perception issue from the marketing audit. **Maintainer verifies by running the live config flow before locking the wording.**

**Diff shape:** ~4 lines of translation per language.

### 8. `sensor.water_level` continuous percent

**File:** `custom_components/sleepme_thermostat/sensor.py`.

**API field:** `status.water_level` — integer 0–100, per developer docs.

Add a new sensor class after the existing diagnostics:

```python
class WaterLevelSensor(_SleepMeDiagnosticSensor):
    """Continuous water-level percent (not the boolean low-level alert)."""

    _attr_icon = "mdi:water-percent"
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: SleepMeUpdateManager,
        device_id: str,
        device_info: DeviceInfo,
    ) -> None:
        super().__init__(
            coordinator,
            device_id,
            device_info,
            suffix="water_level",
            label="Water Level",
        )

    @property
    def native_value(self) -> str | int | None:
        return self.coordinator.data["status"].get("water_level")
```

Register it in `async_setup_entry`. **Note:** the existing low-level `binary_sensor` derives from `status.is_water_low` which is a *separate* field. Both can coexist — the binary sensor is the "act now" trigger, the percent sensor is for charts/automations.

**Tests:** add to `tests/test_climate.py` (or a new `test_sensors.py`) — verify the entity registers and reads `coordinator.data["status"]["water_level"]`. Update `tests/conftest.py::mock_sleepme_client` fixture to include `"water_level": 78` in the canned status.

**Risk:** the API may not actually return `status.water_level` on all firmware versions. The `.get()` returns `None` gracefully, but the entity will show "unknown" — that's fine, just document it. Maintainer verifies on the live device by downloading diagnostics and looking at `coordinator.data.status`.

**Diff shape:** `sensor.py` +25 lines; tests +15 lines; conftest +1 line.

### 9. `sensor.firmware_version`

Same pattern as #8, but reads `about.firmware_version` and goes under `EntityCategory.DIAGNOSTIC`. The field already flows into `device_info["sw_version"]` (HA renders it on the device page), but exposing it as an explicit sensor lets users automate "notify when firmware changes."

```python
class FirmwareVersionSensor(_SleepMeDiagnosticSensor):
    """Reports the current device firmware version as a sensor."""

    _attr_icon = "mdi:chip"

    def __init__(...): ... suffix="firmware_version", label="Firmware Version"

    @property
    def native_value(self) -> str | int | None:
        return self.coordinator.data["about"].get("firmware_version")
```

**Diff shape:** ~20 lines.

### 10. Dead code removal

Per the code-quality agent's grep evidence:

| File:line | Item | Action |
|---|---|---|
| `const.py:1-5` | `APP_API_URL` aliased to `API_URL` with no external import | Pick one; delete the other. |
| `const.py:3` | `DEFAULT_API_HEADERS` — zero references | Delete. |
| `sleepme_api.py:84,86,202,204` | `params` and `input_headers` parameters never passed by any caller | Drop from `api_request` and `_perform_request` signatures. |
| `binary_sensor.py:25` | `_LOGGER = logging.getLogger(__name__)` — never called | Delete the line and the `import logging`. |
| `sensor.py:22` | Same | Delete. |
| `sleepme.py:17` | Same | Delete. |
| `config_flow.py:134-139` | `else: errors["base"] = "no_devices_found"` is unreachable | Document with a `# unreachable` comment OR remove and let `async_step_user`'s check be the only path. |

**Diff shape:** ~30 lines net deletion across 6 files.

### 11. Kill dead `kwargs.get("temperature")` fallback

**File:** `climate.py:163-173`.

`ATTR_TEMPERATURE == "temperature"` — the second `.get` is unreachable.

```diff
     async def async_set_temperature(self, **kwargs: Any) -> None:
         """Set new target temperature."""
         target_temp = kwargs.get(ATTR_TEMPERATURE)
-        if target_temp is None:
-            target_temp = kwargs.get("temperature")
         if target_temp is None:
             raise ServiceValidationError(
                 "Temperature is required",
```

**Diff shape:** 2 lines deleted.

### 12. Strengthen two test holes

**File:** `tests/test_climate.py`.

`test_preset_mode_max_cool` doesn't assert the PATCH actually fired with `-1`. A broken `async_set_preset_mode` that calls `set_temp_level(99)` would pass.

```diff
 async def test_preset_mode_max_cool(
     hass: HomeAssistant, mock_sleepme_client: AsyncMock
 ) -> None:
     """Setting MAX_COOL preset PATCHes the -1 sentinel and updates preset_mode."""
     await _setup(hass)
+    mock_sleepme_client.set_temp_level.reset_mock()
+    mock_sleepme_client.set_device_status.reset_mock()

     await hass.services.async_call(
         CLIMATE_DOMAIN,
         SERVICE_SET_PRESET_MODE,
         {ATTR_ENTITY_ID: ENTITY_ID, ATTR_PRESET_MODE: PRESET_MAX_COOL},
         blocking=True,
     )
     await hass.async_block_till_done()
+
+    mock_sleepme_client.set_device_status.assert_called_once_with("active")
+    mock_sleepme_client.set_temp_level.assert_called_once_with(-1)

     state = hass.states.get(ENTITY_ID)
     assert state.attributes["temperature"] == -1
     assert state.attributes["preset_mode"] == PRESET_MAX_COOL
```

Same pattern for `test_set_hvac_mode_optimistic` — assert `set_device_status.assert_called_once_with("active")`.

**Diff shape:** ~8 lines added to existing tests.

### 13. Version bump to 4.1.0

```diff
 # manifest.json
-  "version": "4.0.0"
+  "version": "4.1.0"
```

Tag `v4.1.0`. Release notes link to this doc and call out:
- Per-account rate limiter (silent correctness fix for multi-device installs).
- `runtime_data` migration (internal).
- New entities: `sensor.*_water_level` (percent), `sensor.*_firmware_version`.
- Renamed in HACS.

## Validation against live device

**Pre-deploy: capture entity_ids** (standard since Phase 2).

```bash
ssh hassio@100.88.154.98 'jq ".data.entities[] | select(.platform == \"sleepme_thermostat\") | .entity_id" /homeassistant/.storage/core.entity_registry' > /tmp/before.txt
```

**Validation matrix:**

1. `pytest --cov-fail-under=80` passes locally; coverage still ≥ 80%.
2. `mypy custom_components/sleepme_thermostat` passes with strict flags.
3. `pre-commit run --all-files` clean.
4. `make deploy-restart HA_HOST=100.88.154.98` succeeds.
5. **Entity registry continuity** — `diff /tmp/before.txt /tmp/after.txt` shows **2 new entities** (`sensor.*_water_level`, `sensor.*_firmware_version`) per device, nothing else changed.
6. **No regressions:** all 3 sleepme entries load cleanly, no `sleepme.*error` lines in `home-assistant.log`.
7. **New entities populate:** check `sensor.dock_pro_ramon_water_level` and `sensor.dock_pro_ramon_firmware_version` in HA → Developer Tools → States. Both should have non-`unknown` values (assuming the API actually returns these fields).
8. **Diagnostics still work:** Settings → SleepMe → ⋮ → Download diagnostics. JSON should now include `water_level` in `coordinator.data.status` and `firmware_version` in `coordinator.data.about`.
9. **Rate-limit sanity:** check that `SleepMeAPI._instances` actually has 1 entry, not 6. From `ha core` python: `from custom_components.sleepme_thermostat.sleepme_api import SleepMeAPI; print(len(SleepMeAPI._instances))`. Expect 1 (all 3 entries share the same token).

## Acceptance / exit criteria

- [ ] `SleepMeAPI._instances` (WeakValueDictionary) deduplicates per `(api_url, token)`. Test verifies.
- [ ] `_compute_backoff` caps `Retry-After` at `BACKOFF_CEILING`. Property test.
- [ ] `_effective_optimistic_temp` retains optimistic value when `coordinator.last_update_success is False`. Test.
- [ ] `entry.runtime_data` replaces `hass.data[DOMAIN][entry.entry_id]` everywhere. No remaining `hass.data[DOMAIN]` reads except for `setdefault` in `async_setup`.
- [ ] `manifest.json` `name` is "SleepMe (Chilipad Dock Pro)"; `hacs.json` matches.
- [ ] README has 3 inline screenshots and a Supported Devices section.
- [ ] `select_device.data.device_id` label updated in EN + ES.
- [ ] `sensor.*_water_level` and `sensor.*_firmware_version` entities exist; `conftest.py` mock includes `water_level` and `firmware_version`.
- [ ] All dead code identified in §10 is gone (grep returns no hits).
- [ ] `climate.py` `async_set_temperature` no longer falls back to `kwargs.get("temperature")`.
- [ ] `test_preset_mode_max_cool` asserts PATCH payload; `test_set_hvac_mode_optimistic` asserts service-status PATCH.
- [ ] `manifest.json` `version` is `4.1.0`; git tag `v4.1.0` created.
- [ ] Live-host validation passes all 9 steps above.
- [ ] All CI matrix jobs green.
- [ ] `docs/ROADMAP.md` Phase 6 row flipped to ✅.

## Risks and open questions

1. **`WeakValueDictionary` lifetime.** If the last `SleepMeClient` referencing a `SleepMeAPI` is GC'd, the deque/lock are dropped — including any in-progress rate-limit accounting. In practice, while an entry is loaded, both the standalone client and the coordinator's client keep references; an entry unload drops both, and the next setup creates a fresh `SleepMeAPI`. That's correct. Worth a comment in the code explaining the lifecycle.

2. **`runtime_data` typing — what about HA <2024.11?** Phase 4's matrix tests HA 2026.1, 2026.3, 2026.5 — all support `runtime_data`. If the maintainer ever wants to support older HA, this is a blocker.

3. **HACS rename behavior.** Renaming the integration in HACS's display does not invalidate existing installs (domain is the key, not name). Worth verifying by `make deploy-restart` and confirming HACS shows the new name without re-installing.

4. **`status.water_level` field availability.** Older firmware may not include this field. The `.get()` returns `None` gracefully (entity shows "unknown"). Maintainer verifies on live device.

5. **Screenshot maintenance.** Screenshots in `docs/images/` will go stale as HA's UI evolves. Worth scheduling a "refresh screenshots" reminder for major HA releases.

6. **Device-picker label change risk.** If the dropdown already shows friendly names (likely), the label tweak is the only visible change. If users have memorized "Device ID" as a label, they may briefly be confused. Low risk.

7. **Test-hole strengthening is purely additive** — no existing test breaks.

## Out of scope (explicit)

| Item | Deferred to |
|---|---|
| Writable `number.brightness_level` | Phase 7+ |
| Writable `select.display_temperature_unit` | Phase 7+ |
| `set_temperature_f` when HA is in Fahrenheit | Phase 7+ (small but needs design — does HA's climate platform pass C or F to us?) |
| Sleep Tracker (ST501NA) platform | Implemented for v4.3.0 after Phase 6 |
| Split-bed (WE) pairing UX | Phase 7+ |
| HA-side Sleep Programs blueprint | Phase 7+ |
| `EntityDescription` refactor + entity/icon translations | Phase 7+ (unblocks HA Gold rules for translation) |
| `async_step_reconfigure` | Phase 7+ |
| `PARALLEL_UPDATES = 1` | Phase 7+ (Silver rule, but no observed harm today) |
| `ir.async_create_issue` repair flows | Phase 7+ |
| Per-account jitter on coordinator poll | Phase 7+ (cosmetic) |
| Skip `async_request_refresh` if recent successful poll | Phase 7+ (depends on #1 being landed first) |
| TypedDict for coordinator data payload | Phase 7+ (was already on the Phase 6 candidate list from Phase 5 doc) |
| EN/ES key-set CI parity check | Phase 7+ |
| `quality_scale.yaml` per-criterion file | Phase 7+ |
| Drop `E731` from ruff ignore | Phase 7+ |
| Refresh `docs/AUDIT.md` against current state | Phase 7+ |
| README badge trim | Phase 7+ |

Phase 6 is correctness + product-polish. Phase 7+ is the feature-expansion arc.
