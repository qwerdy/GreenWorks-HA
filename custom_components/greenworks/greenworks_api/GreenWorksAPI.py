# GreenWorks-Core/Main.py
from dataclasses import dataclass
from zoneinfo import ZoneInfo
from datetime import datetime
import socket
import time
import requests
import json
import logging

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .Records import Login_object, Mower_operating_status, User_info_object, Mower_properties
from .Enums import MowerState


logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 10
# The GreenWorks cloud is only reachable over the internet; DNS hiccups and
# short connection failures happen. Retry briefly instead of failing a poll.
RETRY_ATTEMPTS = 3


class GreenWorksApiError(Exception):
    """Base class for errors raised by the GreenWorks API client."""


class GreenWorksConnectionError(GreenWorksApiError):
    """The GreenWorks cloud could not be reached (DNS/network failure)."""


class UnauthorizedException(GreenWorksApiError):
    """The GreenWorks account credentials were rejected."""


def _root_cause(err: BaseException) -> BaseException:
    """Return the innermost exception of a chained exception."""
    seen: set[int] = set()
    while err.__cause__ is not None and id(err.__cause__) not in seen:
        seen.add(id(err))
        err = err.__cause__
    return err


def _describe_request_error(err: requests.exceptions.RequestException) -> str:
    """Return a short, single-line description of a failed request.

    requests/urllib3 exception messages repeat the full URL and traceback-like
    details for every layer of the chain. That produced huge log entries in
    Home Assistant, so only report the root cause here.
    """
    root = _root_cause(err)
    if isinstance(root, socket.gaierror):
        return f"DNS lookup failed ({root})"
    if isinstance(root, OSError):
        return f"{type(root).__name__}: {root}"
    return f"{type(err).__name__}: {root}"


def _parse_mower_state(value) -> MowerState:
    """Convert the raw API value into a MowerState, tolerating unknown values."""
    try:
        return MowerState(int(value))
    except (TypeError, ValueError):
        logger.debug("Unknown mower main state %r; reporting as DISCONNECTED", value)
        return MowerState.DISCONNECTED


def _parse_timestamp(value, timezone: ZoneInfo) -> datetime | None:
    """Convert a unix timestamp from the API into a datetime, if present."""
    if isinstance(value, (int, float)) and value > 0:
        return datetime.fromtimestamp(value, tz=timezone)
    return None


def _parse_request_time(value, timezone: ZoneInfo) -> datetime | None:
    """Convert an ISO timestamp from the API into a datetime, if present."""
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone)
        except ValueError:
            logger.debug("Could not parse request_time %r", value)
    return None


@dataclass
class Mower:
    id: int
    name: str
    sn: str
    is_online: bool
    properties: Mower_properties
    operating_status: Mower_operating_status
    product_id: int = 0
    model: str = "Greenworks Mower"  # Default model name, can be overridden
    
    def get_all_info(self) -> dict:
        """Return all mower information as a dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "sn": self.sn,
            "is_online": self.is_online,
            "model": self.model,
            "properties": {
                "is_frost_sensor_on": self.properties.is_frost_sensor_on,
                "is_rain_sensor_on": self.properties.is_rain_sensor_on,
                "geofence_latitude": self.properties.geofence_latitude,
                "geofence_longitude": self.properties.geofence_longitude,
                "device_blade_usage_time": self.properties.device_blade_usage_time,
                "device_type_no": self.properties.device_type_no,
                "device_model_name": self.properties.device_model_name,
            },
            "operating_status": {
                "battery_status": self.operating_status.battery_status,
                "mower_main_state": self.operating_status.mower_main_state.name,
                "next_start": self.operating_status.next_start.isoformat() if self.operating_status.next_start else None,
                "request_time": self.operating_status.request_time.isoformat() if self.operating_status.request_time else None,
            }
        }
    
    def print_all_info(self):
        """Print all mower information in a readable format."""
        print(f"\n{'='*50}")
        print(f"Mower: {self.name}")
        print(f"{'='*50}")
        print(f"ID: {self.id}")
        print(f"Serial Number: {self.sn}")
        print(f"Model: {self.model}")
        print(f"Online: {'Yes' if self.is_online else 'No'}")
        print(f"\nProperties:")
        print(f"  - Frost Sensor: {'On' if self.properties.is_frost_sensor_on else 'Off'}")
        print(f"  - Rain Sensor: {'On' if self.properties.is_rain_sensor_on else 'Off'}")
        print(f"  - Geofence: ({self.properties.geofence_latitude}, {self.properties.geofence_longitude})")
        print(f"  - Blade Usage Time: {self.properties.device_blade_usage_time} hours")
        print(f"  - Device Type: {self.properties.device_type_no}")
        print(f"  - Model Name: {self.properties.device_model_name}")
        print(f"\nOperating Status:")
        print(f"  - Battery: {self.operating_status.battery_status}%")
        print(f"  - Main State: {self.operating_status.mower_main_state.name}")
        print(f"  - Next Start: {self.operating_status.next_start}")
        print(f"  - Last Update: {self.operating_status.request_time}")
        print(f"{'='*50}\n")

class GreenWorksAPI:
    """Greenworks - API Wrapper for Greenworks robotic lawn mower."""
    base_url = "https://xapi.globetools.systems/v2/"
    login_info: Login_object
    user_info: User_info_object

    def __init__(self, email: str, password: str, timezone: str):
        """Initialize the GreenWorks class with user credentials."""
        self._email = email
        self.user_password = password
        logger.debug("Initializing GreenWorksAPI client")
        self._session = requests.Session()
        retry = Retry(
            total=RETRY_ATTEMPTS,
            connect=RETRY_ATTEMPTS,
            read=2,
            backoff_factor=0.5,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)
        self._login_user(email, self.user_password)
        self._get_user_info()
        self.UserTimezone = ZoneInfo(timezone)
        logger.debug("Timezone set to %s", timezone)

    def _login_user(self, email: str, password: str):
        logger.debug("Attempting login for %s", email)
        url = f"{self.base_url}user_auth"
        body = {
            "corp_id": "100fa2b00b622800",
            "email": email,
            "password": password,
        }
        try:
            response = self._session.post(url, json=body, timeout=REQUEST_TIMEOUT)
        except requests.exceptions.RequestException as err:
            message = _describe_request_error(err)
            logger.debug("Login request failed: %s", message)
            raise GreenWorksConnectionError(f"Login request failed: {message}") from err

        if response.status_code in (401, 403):
            raise UnauthorizedException(
                f"Login rejected by the GreenWorks API (HTTP {response.status_code})"
            )
        if not response.ok:
            raise GreenWorksApiError(
                f"Login failed with HTTP {response.status_code}"
            )

        try:
            data = response.json()
        except ValueError as err:
            raise GreenWorksApiError("Login response was not valid JSON") from err

        if not data.get("access_token") or not data.get("user_id"):
            raise UnauthorizedException(
                "Login response is missing 'user_id' and/or 'access_token'"
            )

        # Set expiration time for access token (refresh 5 minutes early)
        data["expire_in"] = time.time() + data.get("expire_in", 3500) - 300

        logger.debug("Login successful for user_id=%s", data.get("user_id"))
        self.login_info = Login_object(**data)

    def _get_user_info(self):
        response = self.__request(f"user/{self.login_info.user_id}")
        try:
            payload = response.json()
        except ValueError as err:
            raise GreenWorksApiError("User info response was not valid JSON") from err

        logger.debug(
            "Fetched user info for user_id=%s; keys=%s",
            self.login_info.user_id,
            list(payload.keys()),
        )
        self.user_info = User_info_object(**payload)

    def _get_mower_operating_status(self, product_id: int, mower_id: int) -> Mower_operating_status:
        logger.debug(
            "Requesting mower operating status (product_id=%s, mower_id=%s)",
            product_id,
            mower_id,
        )
        endpoint = f"product/{product_id}/v_device/{mower_id}"
        response = self.__request(endpoint, params={"datapoints": "32"})

        # Feltet "32" er en streng med JSON-indhold
        raw_32 = response.json().get("32", "{}")
        data = json.loads(raw_32).get("request", {})

        status = Mower_operating_status(
            battery_status=data.get("battery_status", -1),
            mower_main_state=_parse_mower_state(data.get("mower_main_state")),
            next_start=_parse_timestamp(data.get("next_start"), self.UserTimezone),
            request_time=_parse_request_time(data.get("request_time"), self.UserTimezone),
        )
        logger.debug(
            "Operating status (mower_id=%s): battery=%s state=%s next_start=%s",
            mower_id,
            status.battery_status,
            getattr(status.mower_main_state, "name", status.mower_main_state),
            status.next_start,
        )
        return status

    def _get_device_properties(self, product_id: int, device_id: int) -> Mower_properties:
        endpoint = f"product/{product_id}/device/{device_id}/property"
        logger.debug(
            "Requesting device properties (product_id=%s, device_id=%s)",
            product_id,
            device_id,
        )
        response = self.__request(endpoint)
        data = response.json()
        logger.debug("Device properties retrieved (device_id=%s); keys=%s", device_id, list(data.keys()))
        return Mower_properties(**data)

    def get_devices(self) -> list[Mower]:
        """Fetch all mowers for the logged in user.

        Raises a GreenWorksApiError subclass when the API cannot be reached or
        returns unusable data. Callers are expected to handle that (the HA
        coordinator turns it into an UpdateFailed) instead of silently getting
        an empty list, which made the mower entities disappear.
        """
        logger.debug("Fetching devices for user_id=%s", self.login_info.user_id)
        endpoint = f"user/{self.login_info.user_id}/subscribe/devices?version=0"
        response = self.__request(endpoint)
        data = response.json()

        devices = data.get("list")
        if not isinstance(devices, list):
            raise GreenWorksApiError("Device list response did not contain a valid 'list'")

        mowers: list[Mower] = []
        for device in devices:
            mower_properties = self._get_device_properties(device.get("product_id"), device.get("id"))
            mower_operating_status = self._get_mower_operating_status(device.get("product_id"), device.get("id"))
            mower = Mower(
                id=device.get("id"),
                name=device.get("name"),
                sn=device.get("sn"),
                is_online=device.get("is_online"),
                properties=mower_properties,
                operating_status=mower_operating_status,
                product_id=device.get("product_id"),
            )
            mowers.append(mower)
            logger.debug(
                "Device loaded id=%s name=%s sn=%s online=%s",
                mower.id,
                mower.name,
                mower.sn,
                mower.is_online,
            )
        return mowers

    def pause_mower(self, mower_id: int, duration: int = 0):
        """
        Placeholder for a method to pause the mower.
        This method should implement the logic to pause the mower.
        """
        # Implement logic to pause the mower
        pass

    def unpause_mower(self, mower_id: int):
        """
        Placeholder for a method to unpause the mower.
        This method should implement the logic to unpause the mower.
        """
        # Implement logic to unpause the mower
        pass

    def dock_mower(self, mower_id: int):

        """
        Placeholder for a method to dock the mower.
        This method should implement the logic to dock the mower.
        """
        # Implement logic to dock the mower
        pass

    def cancel_docking(self, mower_id: int):
        """
        Placeholder for a method to cancel docking of the mower.
        This method should implement the logic to cancel docking of the mower.
        """
        # Implement logic to cancel docking of the mower
        pass

    # private method for requesting data from api
    def __request(
        self,
        endpoint: str,
        params: dict | None = None,
        body: dict | None = None,
        _retry_auth: bool = True,
    ) -> requests.Response:
        if time.time() > self.login_info.expire_in:
            self.refresh_access_token()

        url = f"{self.base_url}{endpoint}"
        headers = {
            "Content-Type": "application/json",
            "Access-Token": self.login_info.access_token,
        }
        logger.debug("GET %s params=%s", url, params)

        try:
            response = self._session.get(
                url,
                json=body or {},
                headers=headers,
                params=params or {},
                timeout=REQUEST_TIMEOUT,
            )
        except requests.exceptions.RequestException as err:
            # DNS hiccups / connection failures are expected for a cloud
            # integration. Keep this quiet; the raised error is reported once
            # by the caller (Home Assistant shows it as an UpdateFailed).
            message = _describe_request_error(err)
            logger.debug("GreenWorks API request failed endpoint=%s: %s", endpoint, message)
            raise GreenWorksConnectionError(
                f"GreenWorks API unreachable ({endpoint}): {message}"
            ) from err

        if _retry_auth and response.status_code == 403:
            try:
                error_code = response.json().get("error", {}).get("code")
            except ValueError:
                error_code = None
            if error_code == 4031022:
                logger.debug(
                    "Access token rejected (4031022); re-logging in and retrying %s", endpoint
                )
                self._login_user(self._email, self.user_password)
                return self.__request(endpoint, params, body, _retry_auth=False)

        try:
            response.raise_for_status()  # Kaster exception på 4xx/5xx
        except requests.exceptions.HTTPError as err:
            status = response.status_code
            body_preview = (response.text or "")[:200]
            logger.warning(
                "GreenWorks API returned HTTP %s for %s (body=%s)",
                status,
                endpoint,
                body_preview,
            )
            raise GreenWorksApiError(
                f"GreenWorks API returned HTTP {status} for {endpoint}"
            ) from err

        return response

    def refresh_access_token(self):
        logger.debug("Refreshing access token")
        url = f"{self.base_url}user/token/refresh"
        body = {
            "refresh_token": self.login_info.refresh_token,
        }
        headers = {
            "Access-Token": self.login_info.access_token
        }
        try:
            response = self._session.post(url, json=body, headers=headers, timeout=REQUEST_TIMEOUT)
        except requests.exceptions.RequestException as err:
            message = _describe_request_error(err)
            logger.debug("Token refresh request failed: %s", message)
            raise GreenWorksConnectionError(f"Token refresh failed: {message}") from err

        logger.debug("Token refresh response status=%s", response.status_code)
        if response.status_code != 200:
            # Re-login if refresh fails
            logger.debug(
                "Token refresh rejected (HTTP %s); falling back to a full login",
                response.status_code,
            )
            self._login_user(self._email, self.user_password)
            return

        try:
            data = response.json()
        except ValueError as err:
            raise GreenWorksApiError("Token refresh response was not valid JSON") from err

        self.login_info.access_token = data.get("access_token")
        self.login_info.refresh_token = data.get("refresh_token")
        self.login_info.expire_in = int(time.time() + 3500)
        logger.debug("Access token refreshed successfully")