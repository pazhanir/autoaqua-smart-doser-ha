"""Async API client for the Auto Aqua cloud service."""

from __future__ import annotations

import logging
import ssl
from typing import Any

import aiohttp

from .const import (
    API_ADD_WRITE_CMD,
    API_BASE_URL,
    API_CHECK_SESSION,
    API_GET_DEVICES,
    API_GET_TANKS,
    API_LOGIN,
)

_LOGGER = logging.getLogger(__name__)


class AutoAquaApiError(Exception):
    """Base exception for AutoAqua API errors."""


class AuthenticationError(AutoAquaApiError):
    """Authentication failed (bad credentials or expired token)."""


class ApiConnectionError(AutoAquaApiError):
    """Could not connect to the AutoAqua cloud API."""


class AutoAquaApi:
    """Async client for the AutoAqua Aqualine cloud API.

    Handles JWT authentication with automatic re-login on 401,
    SSL verification bypass (server uses IP with self-signed cert),
    and the standard {Code, Message, Data} response envelope.
    """

    def __init__(
        self,
        email: str,
        password: str,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        """Initialize the API client.

        Args:
            email: AutoAqua account email.
            password: AutoAqua account password.
            session: Optional aiohttp session (HA provides one).
        """
        self._email = email
        self._password = password
        self._session = session
        self._close_session = False
        self._token: str | None = None
        self._session_id: str | None = None

    @staticmethod
    def _ssl_context() -> ssl.SSLContext:
        """SSL context that skips certificate verification.

        The AutoAqua server runs on a bare IP (3.141.77.242) with a
        certificate that doesn't match, so we must disable verification.
        """
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    def _get_session(self) -> aiohttp.ClientSession:
        """Return the aiohttp session, creating one if needed."""
        if self._session is None:
            self._session = aiohttp.ClientSession()
            self._close_session = True
        return self._session

    def _headers(self, with_auth: bool = True) -> dict[str, str]:
        """Build request headers."""
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "User-Agent": "okhttp/4.11.0",
        }
        if with_auth and self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    # ------------------------------------------------------------------
    # Core request method
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        auth_required: bool = True,
        retry_auth: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Make an API request with automatic re-authentication on 401.

        Returns the parsed JSON response dict.
        Raises ApiConnectionError on network issues,
               AuthenticationError on auth failures.
        """
        url = f"{API_BASE_URL}{endpoint}"
        session = self._get_session()

        try:
            async with session.request(
                method,
                url,
                headers=self._headers(with_auth=auth_required),
                ssl=self._ssl_context(),
                **kwargs,
            ) as resp:
                # Auto re-login on 401 (token expired, ~3.6 min lifetime)
                if resp.status == 401 and retry_auth and auth_required:
                    _LOGGER.debug("Token expired, re-authenticating")
                    await self.authenticate()
                    return await self._request(
                        method,
                        endpoint,
                        auth_required=True,
                        retry_auth=False,
                        **kwargs,
                    )

                if resp.status == 401:
                    raise AuthenticationError("Authentication failed after retry")

                resp.raise_for_status()
                data: dict[str, Any] = await resp.json()
                return data

        except AuthenticationError:
            raise
        except aiohttp.ClientError as err:
            raise ApiConnectionError(
                f"Error communicating with AutoAqua API: {err}"
            ) from err

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def authenticate(self) -> dict[str, Any]:
        """Login with email/password and store the JWT access token.

        Returns the user data dict from the login response.
        """
        payload = {
            "account": self._email,
            "password": self._password,
            "device_brand": "android",
            "device_id": "ha_autoaqua_doser",
            "notice_token": "",
        }

        data = await self._request(
            "POST", API_LOGIN, json=payload, auth_required=False
        )

        if data.get("Code") != 0:
            msg = data.get("Message", "Unknown error")
            raise AuthenticationError(f"Login failed: {msg}")

        user_data: dict[str, Any] = data.get("Data", {})
        self._token = user_data.get("access_token")
        self._session_id = user_data.get("session_id")

        if not self._token:
            raise AuthenticationError("No access token in login response")

        _LOGGER.debug("Authenticated as %s", self._email)
        return user_data

    # ------------------------------------------------------------------
    # Device & tank queries
    # ------------------------------------------------------------------

    async def get_devices(self) -> list[dict[str, Any]]:
        """Fetch all devices for the logged-in user.

        Each device dict contains keys like:
          device_id, device_name, device_type, device_mac,
          device_online_status (1=online), device_fw_hex,
          device_status_hex, tank_name, calibrate1-4,
          pump_name1-4, etc.
        """
        data = await self._request("GET", API_GET_DEVICES)
        if data.get("Code") != 0:
            raise AutoAquaApiError(f"GetDevices failed: {data.get('Message')}")
        return data.get("Data", [])

    async def get_tanks(self) -> list[dict[str, Any]]:
        """Fetch all tanks for the logged-in user."""
        data = await self._request("GET", API_GET_TANKS)
        if data.get("Code") != 0:
            raise AutoAquaApiError(f"GetTanks failed: {data.get('Message')}")
        return data.get("Data", [])

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def send_command(self, device_id: str, command_hex: str) -> bool:
        """Send a hex command to a device via AddWriteCmd.

        Args:
            device_id: Device MAC / ID (e.g. "34B7DA28DE69").
            command_hex: Hex string command (e.g. dose or status poll).

        Returns True if the server acknowledged with "OK".
        """
        payload = {
            "device_id": device_id,
            "type": "0",
            "write_cmd": command_hex,
        }
        data = await self._request("POST", API_ADD_WRITE_CMD, json=payload)
        if data.get("Code") != 0:
            raise AutoAquaApiError(f"AddWriteCmd failed: {data.get('Message')}")
        return data.get("Data") == "OK"

    async def check_session(self) -> bool:
        """Check if the current session is still valid."""
        if not self._session_id:
            return False
        payload = {"session_id": self._session_id}
        try:
            data = await self._request("POST", API_CHECK_SESSION, json=payload)
            return data.get("Code") == 0 and data.get("Data") is True
        except AutoAquaApiError:
            return False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the HTTP session if we created it."""
        if self._close_session and self._session:
            await self._session.close()
            self._session = None
