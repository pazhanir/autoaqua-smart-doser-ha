"""Decode the device status frame (device_status_hex) reported by the cloud.

Layout observed on firmware 25.2.14 (Smart Doser 2 and Smart Doser 4), e.g.
"8020000100B02E0000000000000001000305":

  80 20 00 01   header (opcode 0x20 = status response)
  byte 1        low nibble  = pumps currently running (bit n-1 = pump n)
                high nibble = optical liquid sensor sees no liquid (bit n-1 = pump n)
  byte 13       phase: 0x00 dose started, 0x04 manual run, 0x05 finished, 0x01 idle

The liquid bits are only reported while the doser is active. Idle frames
(phase 0x01) always carry 0, so they say nothing about the liquid state.
"""

from __future__ import annotations

from typing import NamedTuple

STATUS_HEADER = "80200001"
PHASE_IDLE = 0x01
PAYLOAD_LEN = 14


class StatusFrame(NamedTuple):
    """Decoded status frame."""

    running_mask: int
    liquid_missing_mask: int
    phase: int

    @property
    def active(self) -> bool:
        """Return True when the frame carries meaningful liquid bits."""
        return self.phase != PHASE_IDLE

    def liquid_missing(self, pump: int) -> bool:
        """Return True when the sensor of the given pump (1-4) sees no liquid."""
        return bool(self.liquid_missing_mask >> (pump - 1) & 1)


def parse_status_hex(status_hex: str | None) -> StatusFrame | None:
    """Parse a status frame, or return None if it is missing or malformed."""
    if not status_hex or not status_hex.upper().startswith(STATUS_HEADER):
        return None
    try:
        payload = bytes.fromhex(status_hex[len(STATUS_HEADER):])
    except ValueError:
        return None
    if len(payload) < PAYLOAD_LEN:
        return None
    return StatusFrame(payload[1] & 0x0F, payload[1] >> 4, payload[PAYLOAD_LEN - 1])
