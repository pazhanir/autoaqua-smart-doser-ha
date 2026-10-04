"""Checks for the status frame parser, using frames captured from real devices.

Run with: python3 tests/test_status.py (no Home Assistant install needed).
"""

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "status",
    Path(__file__).resolve().parents[1] / "custom_components/autoaqua_doser/status.py",
)
status = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(status)


def test_idle_frame_has_no_liquid_info():
    frame = status.parse_status_hex("802000010000000000000000000001000301")
    assert frame is not None and not frame.active
    assert frame.running_mask == 0 and frame.liquid_missing_mask == 0


def test_pumps_1_2_4_dry_after_manual_run():
    # Matched the AquaLine app showing P1, P2 and P4 without liquid.
    frame = status.parse_status_hex("8020000100B02E0000000000000001000305")
    assert frame.active and frame.phase == 0x05
    assert [frame.liquid_missing(p) for p in (1, 2, 3, 4)] == [True, True, False, True]


def test_pump_4_running_while_1_and_2_dry():
    frame = status.parse_status_hex("8020000100380000000000003C0001000304")
    assert frame.running_mask == 0x08 and frame.phase == 0x04
    assert [frame.liquid_missing(p) for p in (1, 2, 3, 4)] == [True, True, False, False]


def test_scheduled_dose_pump_2_with_pump_3_dry():
    frame = status.parse_status_hex("802000010042000000000000000001000300")
    assert frame.running_mask == 0x02 and frame.phase == 0x00
    assert frame.liquid_missing(3) and not frame.liquid_missing(2)


def test_malformed_frames():
    for bad in (None, "", "unavailable", "80200001", "8099000119020E0000", "80200001ZZ"):
        assert status.parse_status_hex(bad) is None


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
