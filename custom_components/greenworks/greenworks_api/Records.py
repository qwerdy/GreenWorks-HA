from dataclasses import dataclass
from .Enums import MowerState
from datetime import datetime
@dataclass
class Mower_properties:
    is_frost_sensor_on: bool = False
    is_rain_sensor_on: bool = False
    geofence_latitude: float = 0.0
    geofence_longitude: float = 0.0
    device_blade_usage_time: int = 0
    device_type_no: str = ""
    device_model_name: str = ""

@dataclass
class Mower_info:
    subscribe_date: str
    is_active: bool
    role: int
    last_login: str
    active_code: str
    active_date: str
    groups: str
    mcu_version: int
    firmware_version: int
    source: int
    mac: str
    product_id: str
    access_key: int
    authority: str
    name: str
    authorize_code: str
    id: int
    is_online: bool
    sn: str

@dataclass
class Mower_operating_status:
    battery_status: int
    mower_main_state: MowerState
    next_start: datetime
    request_time: datetime
    
@dataclass
class Login_object:
    access_token: str
    refresh_token: str
    user_id: int
    expire_in: int
    authorize: str

@dataclass
class User_info_object:
    gender: int
    active_date: str
    source: int
    passwd_inited: bool
    is_vaild: bool
    nickname: str
    id: int
    create_date: str
    email: str
    region_id: int
    authorize_code: str
    corp_id: str
    privacy_code: str
    account: str
    age: int
    status: int