import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

# Add custom_components/greenworks to path to import greenworks_api directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'custom_components', 'greenworks'))

from greenworks_api.GreenWorksAPI import GreenWorksAPI
from greenworks_api.Records import Login_object, User_info_object

from unittest import mock
from requests.exceptions import RequestException
import time


def test_login_and_user_info_live():
    greenworks = GreenWorksAPI(os.getenv("EMAIL"), os.getenv("PASSWORD"), "Europe/Copenhagen") # type: ignore
    assert greenworks.user_info.email == os.getenv("EMAIL")
    assert greenworks.login_info.access_token is not None
    assert greenworks.login_info.user_id is not None


def test_get_devices_live():
    greenworks = GreenWorksAPI(os.getenv("EMAIL"), os.getenv("PASSWORD"), "Europe/Copenhagen") # type: ignore
    mowers = greenworks.get_devices()
    assert len(mowers) > 0, "No devices found."
    for device in mowers:
        assert device.id is not None, "Device ID is None."
        assert device.name is not None, "Device name is None."
        assert device.sn is not None, "Device SN is None."
        assert device.is_online is not None, "Device online status is None."
        assert device.properties is not None, "Device properties are None."
        assert device.operating_status is not None, "Device operating status is None."
        # Print device information for debugging
        print(f"Device Name: {device.name}, SN: {device.sn}, Device ID: {device.id}, Online: {device.is_online}")
        print(f"Device Battery Status: {device.operating_status.battery_status}")
        print(f"Device Main State: {device.operating_status.mower_main_state.name}")
        print(f"Next Start: {device.operating_status.next_start}")

def test_refresh_access_token_success():
    """Ensure refresh_access_token updates tokens on success and doesn't re-login."""
    # Mock login (first POST) and refresh (second POST), and user info (__request)
    with mock.patch('greenworks_api.GreenWorksAPI.requests.post') as mock_post, \
         mock.patch('greenworks_api.GreenWorksAPI.GreenWorksAPI._GreenWorksAPI__request') as mock_req:

        # First POST: login
        login_resp = mock.Mock()
        login_resp.status_code = 200
        login_resp.json.return_value = {
            "access_token": "old-access",
            "refresh_token": "old-refresh",
            "user_id": 123,
            "expire_in": 3600,
            "authorize": "RW",
        }
        # Second POST: refresh
        refresh_resp = mock.Mock()
        refresh_resp.status_code = 200
        refresh_resp.json.return_value = {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
        }
        mock_post.side_effect = [login_resp, refresh_resp]

        # __request for user info
        req_resp = mock.Mock()
        req_resp.json.return_value = {
            "gender": 0,
            "active_date": "2025-01-01T00:00:00Z",
            "source": 0,
            "passwd_inited": True,
            "is_vaild": True,
            "nickname": "tester",
            "id": 123,
            "create_date": "2025-01-01T00:00:00Z",
            "email": "tester@example.com",
            "region_id": 0,
            "authorize_code": "abcd",
            "corp_id": "corp",
            "privacy_code": "privacy",
            "account": "tester",
            "age": 30,
            "status": 1,
        }
        mock_req.return_value = req_resp

        api = GreenWorksAPI("tester@example.com", "password", "Europe/Copenhagen")
        old_expire = api.login_info.expire_in

        api.refresh_access_token()

        assert api.login_info.access_token == "new-access"
        assert api.login_info.refresh_token == "new-refresh"
        assert api.login_info.expire_in > old_expire
        # Two POSTs (login + refresh), no extra login
        assert mock_post.call_count == 2

def test_refresh_access_token_refresh_fail_relogin_success():
    """When refresh returns non-200, the client performs a re-login and updates tokens."""
    with mock.patch('greenworks_api.GreenWorksAPI.requests.post') as mock_post, \
         mock.patch('greenworks_api.GreenWorksAPI.GreenWorksAPI._GreenWorksAPI__request') as mock_req:

        # POST sequence: initial login OK, refresh fails, re-login OK
        login_resp1 = mock.Mock()
        login_resp1.status_code = 200
        login_resp1.json.return_value = {
            "access_token": "old-access",
            "refresh_token": "old-refresh",
            "user_id": 123,
            "expire_in": 3600,
            "authorize": "RW",
        }
        refresh_fail = mock.Mock()
        refresh_fail.status_code = 401
        refresh_fail.text = "unauthorized"
        refresh_fail.json.return_value = {"error": "unauthorized"}
        login_resp2 = mock.Mock()
        login_resp2.status_code = 200
        login_resp2.json.return_value = {
            "access_token": "relogin-access",
            "refresh_token": "relogin-refresh",
            "user_id": 123,
            "expire_in": 3600,
            "authorize": "RW",
        }
        mock_post.side_effect = [login_resp1, refresh_fail, login_resp2]

        # __request for user info
        req_resp = mock.Mock()
        req_resp.json.return_value = {
            "gender": 0,
            "active_date": "2025-01-01T00:00:00Z",
            "source": 0,
            "passwd_inited": True,
            "is_vaild": True,
            "nickname": "tester",
            "id": 123,
            "create_date": "2025-01-01T00:00:00Z",
            "email": "tester@example.com",
            "region_id": 0,
            "authorize_code": "abcd",
            "corp_id": "corp",
            "privacy_code": "privacy",
            "account": "tester",
            "age": 30,
            "status": 1,
        }
        mock_req.return_value = req_resp

        api = GreenWorksAPI("tester@example.com", "password", "Europe/Copenhagen")
        # Perform refresh which will fail and trigger re-login
        api.refresh_access_token()

        # Three POST calls: login, refresh fail, re-login
        assert mock_post.call_count == 3
        # Tokens updated from re-login response
        assert api.login_info.access_token == "relogin-access"
        assert api.login_info.refresh_token == "relogin-refresh"

if __name__ == "__main__":
    # Always run the unit (mocked) test
    test_refresh_access_token_success()
    test_refresh_access_token_refresh_fail_relogin_success()

    # Run live tests only when credentials are provided
    if os.getenv("EMAIL") and os.getenv("PASSWORD"):
        test_login_and_user_info_live()
        test_get_devices_live()
        print("All tests passed.")
    else:
        print("Skipping live API tests: EMAIL/PASSWORD not set. Mocked success test passed.")
