# GreenWorks-Core/Main.py
from dataclasses import dataclass
from zoneinfo import ZoneInfo
from datetime import datetime
import time
import requests
import json
import logging
from .Records import Login_object, Mower_operating_status, User_info_object, Mower_properties
from .Enums import MowerState


logger = logging.getLogger(__name__)


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
        self.user_password = password
        logger.info("Initializing GreenWorksAPI client")
        self._login_user(email, self.user_password)
        self._get_user_info()
        self.UserTimezone = ZoneInfo(timezone)
        logger.debug("Timezone set to %s", timezone)

    def _login_user(self, email: str, password: str):
        try:
            logger.info("Attempting login for %s", email)
            # Send POST request to the API
            url = f"{self.base_url}user_auth"
            body = {
                "corp_id": "100fa2b00b622800",
                "email": email,
                "password": password,
            }
            response = requests.post(url, json=body, timeout=10)
            logger.info("Login response status=%s", response.status_code)
            data = response.json()

            data["expire_in"] = time.time() + data["expire_in"] - 300  # Set expiration time for access token

            # Eventuelt check for nødvendige felter
            if "user_id" not in data or "access_token" not in data:
                raise ValueError("Login-svar mangler nødvendige felter: 'user_id' og/eller 'access_token'")

            logger.info("Login successful for user_id=%s", data.get("user_id"))
            self.login_info = Login_object(**data)

        except Exception as e:
            logger.exception("Login failed: %s", e)
            raise RuntimeError(f"Fejl ved login: {e}") from e

    def _get_user_info(self):
        try:
            response = self.__request(f"user/{self.login_info.user_id}")
            try:
                payload = response.json()
            except ValueError:
                payload = {}

            logger.info("Fetched user info for user_id=%s; keys=%s", self.login_info.user_id, list(payload.keys()))
            data = payload

            self.user_info = User_info_object(**data)

        except Exception as e:
            logger.exception("Failed fetching user info: %s", e)
            raise RuntimeError(f"Fejl") from e

    def _get_mower_operating_status(self, product_id: int, mower_id: int) -> Mower_operating_status:
        try:
            logger.info("Requesting mower operating status (product_id=%s, mower_id=%s)", product_id, mower_id)
            endpoint = f"product/{product_id}/v_device/{mower_id}"
            response = self.__request(endpoint, params={"datapoints": "32"})
            response.raise_for_status()  # Stopper ved 4xx/5xx


            # Feltet "32" er en streng med JSON-indhold
            raw_32 = response.json().get("32", "{}")
            parsed_32 = json.loads(raw_32)
            data = parsed_32.get("request", {})

            status = Mower_operating_status(
                battery_status=data.get("battery_status", -1),
                mower_main_state=MowerState(data.get("mower_main_state", -1)),
                next_start=datetime.fromtimestamp(data.get("next_start", ""), tz=self.UserTimezone),
                request_time=datetime.fromisoformat(data.get("request_time", "").replace("Z", "+00:00")).astimezone(self.UserTimezone)
            )
            logger.info(
                "Operating status (mower_id=%s): battery=%s state=%s next_start=%s",
                mower_id,
                status.battery_status,
                getattr(status.mower_main_state, "name", status.mower_main_state),
                status.next_start,
            )
            return status
        except Exception as e:
            logger.exception("Error getting mower operating status (product_id=%s, mower_id=%s): %s", product_id, mower_id, e)
            raise RuntimeError(f"Fejl ved hentning af plæneklipperens driftsstatus: {e}") from e

    def _get_device_properties(self, product_id: int, device_id: int) -> Mower_properties:
        endpoint = f"product/{product_id}/device/{device_id}/property"

        try:
            logger.info("Requesting device properties (product_id=%s, device_id=%s)", product_id, device_id)
            response = self.__request(endpoint)
            response.raise_for_status()  
            
            data = response.json()
            logger.debug("Device properties retrieved (device_id=%s); keys=%s", device_id, list(data.keys()))
            return Mower_properties(**data) 

        except requests.exceptions.RequestException as e:
            logger.exception("API error when fetching device properties: %s", e)
            raise RuntimeError(f"Fejl under API-kald til {self.base_url}{endpoint}: {e}") from e

    def get_devices(self) -> list[Mower]:
        Mowers: list[Mower] = []
        try:
            logger.info("Fetching devices for user_id=%s", self.login_info.user_id)
            endpoint = f"user/{self.login_info.user_id}/subscribe/devices?version=0"
            response = self.__request(endpoint)
            response.raise_for_status()  # Stopper hvis status != 2xx

            data = response.json()

            # Tjek at 'list' findes i JSON og er en liste
            devices = data.get("list")
            if not isinstance(devices, list):
                raise ValueError("JSON-svar indeholder ikke en gyldig 'list' af enheder")
            
            # Returner en liste af Mower objekter
            for device in devices:
                mower_properties = self._get_device_properties(device.get("product_id"), device.get("id"))
                if mower_properties is None:
                    raise ValueError(f"Kunne ikke hente egenskaber for enhed med ID {device.get('id')}")
                mower_operating_status = self._get_mower_operating_status(device.get("product_id"), device.get("id"))
                if mower_operating_status is None:
                    raise ValueError(f"Kunne ikke hente tilstand for enhed med ID {device.get('id')}")
                # Opret Mower objekt med de hentede data
                mower = Mower(
                    id=device.get("id"),
                    name=device.get("name"),
                    sn=device.get("sn"),
                    is_online=device.get("is_online"),
                    properties=mower_properties,
                    operating_status=mower_operating_status,
                    product_id=device.get("product_id")
                )
                # Tilføj Mower objektet til listen
                Mowers.append(mower)
                logger.info(
                    "Device loaded id=%s name=%s sn=%s online=%s",
                    mower.id,
                    mower.name,
                    mower.sn,
                    mower.is_online,
                )
            return Mowers  # Returner listen af Mower objekter
        
        except Exception as e:
            logger.exception("Failed to fetch devices: %s", e)
            return []

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
    def __request(self, endpoint:str, params={}, body={}):
        if time.time() > self.login_info.expire_in:
            self.refresh_access_token()
        try:
            url = f"{self.base_url}{endpoint}"
            header = {'Content-Type':'application/json', "Access-Token": self.login_info.access_token}
            logger.debug("GET %s params=%s", url, params)
            
            logger.debug("GET %s body=%s headers=%s", url, body, header)
            response = requests.get(url,json=body, headers=header,params=params,timeout=10)
            logger.debug("Response status=%s for %s", response.status_code, url)
            if response.status_code == 403 and response.json().get("error", {}).get("code") == 4031022:
                logger.warning("Access token rejected (4031022). Re-logging and retrying request: %s", endpoint)
                self._login_user(self.user_info.email, self.user_password)
                response = self.__request(endpoint, params, body)


            response.raise_for_status()  # Kaster exception på 4xx/5xx
            return response
    
        except requests.exceptions.RequestException as e:
            # More context for troubleshooting
            resp = getattr(e, "response", None)
            status = getattr(resp, "status_code", "n/a")
            body_preview = (getattr(resp, "text", "") or "")[:500]
            logger.exception("Request failed endpoint=%s status=%s body=%s error=%s", endpoint, status, body_preview, e)
            raise RuntimeError(f"Fejl under API-kald til {self.base_url}{endpoint}: status={status} error={e}") from e
        
    def refresh_access_token(self):
        logger.info("Refreshing access token")
        url = f"{self.base_url}user/token/refresh"
        body = {
            "refresh_token": self.login_info.refresh_token,
        }
        headers = {
            "Access-Token": self.login_info.access_token
        }
        try:
            logger.debug("POST %s body=%s headers=%s", url, body, headers)
            response = requests.post(url, json=body, headers=headers, timeout=10)
            logger.info("Token refresh response status=%s", response.status_code)
            if response.status_code != 200:
                logger.warning("Failed to refresh access token: status=%s body=%s", response.status_code, response.text)
                self._login_user(self.user_info.email, self.user_password)  # Re-login if refresh fails
                logger.info("Performed re-login after refresh failure")
                return
            data = response.json()
            self.login_info.access_token = data.get("access_token")
            self.login_info.refresh_token = data.get("refresh_token")
            self.login_info.expire_in = int(time.time() + 3500)
            logger.info("Access token refreshed successfully")

        except requests.exceptions.RequestException as e:
            logger.exception("HTTP error during token refresh: %s", e)
            raise RuntimeError(f"Fejl under API-kald til {url}: {e}") from e

        except ValueError as e:
            logger.exception("Invalid JSON during token refresh: %s", e)
            raise RuntimeError(f"Ugyldigt JSON-svar fra {url}: {e}") from e

        except TypeError as e:
            logger.exception("Type error during token refresh: %s", e)
            raise RuntimeError(f"Fejl ved oprettelse af mower_info_object: {e}") from e

        except Exception as e:
            logger.exception("Unexpected error during token refresh: %s", e)
            raise RuntimeError(f"Uventet fejl under API-kald til {url}: {e}") from e

        
class UnauthorizedException(Exception):
    pass