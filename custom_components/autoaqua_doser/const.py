"""Constants for the Auto Aqua Smart Doser integration."""

from datetime import timedelta

DOMAIN = "autoaqua_doser"
MANUFACTURER = "Auto Aqua"
MODEL = "Smart Doser 4"

# API Configuration
API_BASE_URL = "https://3.141.77.242:6002"
API_LOGIN = "/api/v1/Users/Login"
API_GET_DEVICES = "/api/v1/SDDevice/GetDevices"
API_GET_TANKS = "/api/v1/SDTank/GetTanks"
API_ADD_WRITE_CMD = "/api/v1/SDDevice/AddWriteCmd"
API_GET_APP_SETTING = "/api/Home/getAppSettiog"
API_CHECK_SESSION = "/api/v1/Users/CheckLoginUserSessionId"

# Polling
DEFAULT_SCAN_INTERVAL = timedelta(seconds=60)

# Config keys
CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_DEVICE_ID = "device_id"
CONF_DEVICE_NAME = "device_name"

# Protocol constants
FRAME_START = 0x3C  # '<'
FRAME_END = 0x3E    # '>'
DEVICE_ADDR = 0x03
OPCODE_STATUS = 0x20
OPCODE_DOSE = 0x21
DOSE_PAYLOAD_LEN = 0x0B  # 11 bytes

# Pump positions (byte offset from start of payload data, after opcode + reserved byte)
# Each pump gets 2 bytes (uint16 little-endian), packed sequentially
# Layout: 3C 03 00 0B 21 00 [P1L P1H] [P2L P2H] [P3L P3H] [P4L P4H] 00 3E
PUMP_COUNT = 4
PUMP_BYTE_OFFSETS = {1: 0, 2: 2, 3: 4, 4: 6}  # Byte offset within the pump data area

# Dosing limits
DOSE_MIN_ML = 1
DOSE_MAX_ML = 999

# Status poll command
STATUS_POLL_CMD = "3C03000220003E"


def build_dose_command(pump: int, ml: int) -> str:
    """Build a hex dose command string for the given pump and ml amount.

    Args:
        pump: Pump number (1-4).
        ml: Milliliters to dose (1-999).

    Returns:
        Hex string of the dose command.

    Raises:
        ValueError: If pump or ml is out of range.
    """
    if pump < 1 or pump > PUMP_COUNT:
        raise ValueError(f"Pump must be 1-{PUMP_COUNT}, got {pump}")
    if ml < DOSE_MIN_ML or ml > DOSE_MAX_ML:
        raise ValueError(f"ML must be {DOSE_MIN_ML}-{DOSE_MAX_ML}, got {ml}")

    # Build the 11-byte payload: opcode(1) + reserved(1) + pump_data(8) + padding(1)
    payload = [OPCODE_DOSE, 0x00] + [0x00] * 8 + [0x00]

    # Each pump has 2 bytes (little-endian uint16)
    offset = 2 + PUMP_BYTE_OFFSETS[pump]
    payload[offset] = ml & 0xFF          # Low byte
    payload[offset + 1] = (ml >> 8) & 0xFF  # High byte

    # Build the full frame
    frame = [FRAME_START, DEVICE_ADDR, 0x00, DOSE_PAYLOAD_LEN] + payload + [FRAME_END]
    return "".join(f"{b:02X}" for b in frame)
