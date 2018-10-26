"""Library to handle connection with mill."""
# Based on https://pastebin.com/53Nk0wJA and Postman capturing from the app
# All requests are send unencrypted from the app :(
import asyncio
import datetime as dt
import hashlib
import json
import logging
import random
import string
import time

import aiohttp
import async_timeout


API_ENDPOINT = 'https://api.millheat.com'
DEFAULT_TIMEOUT = 10
MIN_TIME_BETWEEN_UPDATES = dt.timedelta(seconds=10)
REQUEST_TIMEOUT = '300'


_LOGGER = logging.getLogger(__name__)


class Mill:
    """Class to comunicate with the Mill api."""
    # pylint: disable=too-many-instance-attributes

    def __init__(self, access_key, secret_token, username, password,
                 timeout=DEFAULT_TIMEOUT,
                 websession=None):
        """Initialize the Mill connection."""
        if websession is None:
            async def _create_session():
                return aiohttp.ClientSession()
            loop = asyncio.get_event_loop()
            self.websession = loop.run_until_complete(_create_session())
        else:
            self.websession = websession
        self._timeout = timeout
        self._access_key = access_key
        self._secret_token = secret_token
        self._username = username
        self._password = password
        self._authorization_code = None
        self._user_id = None
        self._access_token = None
        self._token_expiry = None
        self._refresh_token = None
        self._refresh_expiry = None
        self.rooms = {}
        self.heaters = {}
        self._throttle_time = None

    async def retrieve_authorization_code(self):
        """Connect to Mill."""
        url = API_ENDPOINT + '/share/applyAuthCode'
        headers = {
            "access_key": self._access_key,
            "secret_token": self._secret_token
        }
        try:
            with async_timeout.timeout(self._timeout):
                resp = await self.websession.post(url,
                                                  headers=headers)
        except (asyncio.TimeoutError, aiohttp.ClientError) as err:
            _LOGGER.error("Error connecting to Mill: %s", err)
            return False

        body = await resp.json()
        if 'errorCode' in body:
            if body['errorCode'] == 101:
                _LOGGER.error("Remote system error")
                return None
            if body['errorCode'] == 102:
                _LOGGER.error("UDS error")
                return None
            if body['errorCode'] == 201:
                _LOGGER.error('Wrong access key')
                return False

        if resp.status == 200 and body['success'] == True:
            if 'authorization_code' in resp.headers:
                self._authorization_code = resp.headers['authorization_code']
                return True
        return False


    async def retrieve_access_token(self):
        """Connect to Mill."""
        url = API_ENDPOINT + '/share/applyAccessToken'
        headers = {
            'authorization_code': self._authorization_code
        }
        params = {
            'username': self._username,
            'password': self._password
        }
        try:
            with async_timeout.timeout(self._timeout):
                resp = await self.websession.post(url,
                                                  headers=headers,
                                                  params=params)
        except (asyncio.TimeoutError, aiohttp.ClientError) as err:
            _LOGGER.error("Error connecting to Mill: %s", err)
            return False

        body = await resp.json()
        if 'errorCode' in body:
            if body['errorCode'] == 101:
                _LOGGER.error("Remote system error")
                return None
            if body['errorCode'] == 102:
                _LOGGER.error("UDS error")
                return None
            if body['errorCode'] == 221:
                _LOGGER.error('User does not exist')
                return False
            if body['errorCode'] == 222:
                _LOGGER.error('Authorization_code is invalid')
                return False
            if body['errorCode'] == 223:
                _LOGGER.error('Application account has lapsed')
                return False

        if resp.status == 200 and body['success']:
            data = body['data']
            if 'access_token' in data:
                self._access_token = data['access_token']
                _LOGGER.debug('Got access token: ', self._access_token)
            if 'refresh_token' in data:
                self._refresh_token = data['refresh_token']
                _LOGGER.debug('Got refresh token: ', self._refresh_token)
            if 'expireTime' in data:
                self._token_expiry = dt.datetime.fromtimestamp(float(data['expireTime'])/1000)
                _LOGGER.debug('Got token expiry: ', self._token_expiry)
            if 'refresh_expireTime' in data:
                self._refresh_expiry = dt.datetime.fromtimestamp(float(data['refresh_expireTime'])/1000)
                _LOGGER.debug('Got refresh expiry: %s', self._refresh_expiry)
            return True
        return False

    def sync_connect(self):
        """Initiate the Mill connection."""
        loop = asyncio.get_event_loop()
        task = loop.create_task(self.retrieve_authorization_code())
        loop.run_until_complete(task)
        loop = asyncio.get_event_loop()
        task = loop.create_task(self.retrieve_access_token())
        loop.run_until_complete(task)

    async def close_connection(self):
        """Terminate the Mill connection."""
        await self.websession.close()

    def sync_close_connection(self):
        """Close the Mill connection."""
        loop = asyncio.get_event_loop()
        task = loop.create_task(self.close_connection())
        loop.run_until_complete(task)

    async def token(self):
        if not self._access_token:
            raise Exception('Not connected')

        if (self._token_expiry - dt.datetime.now()).seconds > 7200:
            return self._access_token

        if (self._refresh_expiry - dt.datetime.now()).seconds < 0:
            _LOGGER.debug("Refresh token expired, reauthenticating")
            self.sync_connect()
            return self._access_token

        url = API_ENDPOINT + '/share/refreshtoken'
        params = {'refreshtoken': self._refresh_token}
        try:
            with async_timeout.timeout(self._timeout):
                resp = await self.websession.post(url,
                                                  params=params)
        except (asyncio.TimeoutError, aiohttp.ClientError) as err:
            _LOGGER.error("Error connecting to Mill: %s", err)
            return None

        body = await resp.json()
        if 'errorCode' in body:
            if body['errorCode'] == 101:
                _LOGGER.error("Remote system error")
                return None
            if body['errorCode'] == 102:
                _LOGGER.error("UDS error")
                return None
            if body['errorCode'] == 241:
                _LOGGER.error("Refresh token is wrong or expired")
                return None
            if body['errorCode'] == 242:
                _LOGGER.error("Refresh token is wrong")
                return None
            if body['errorCode'] == 243:
                _LOGGER.error("Application account has lapsed")
                return None

        if resp.status == 200 and body['success']:
            data = body['data']
            if 'access_token' in data:
                self._access_token = data['access_token']
                _LOGGER.debug('Got access token: %s', self._access_token)
            if 'refresh_token' in data:
                self._refresh_token = data['refresh_token']
                _LOGGER.debug('Got refresh token: %s', self._refresh_token)
            if 'expireTime' in data:
                self._token_expiry = dt.datetime.fromtimestamp(float(data['expireTime'])/1000)
                _LOGGER.debug('Got token expiry: %s', self._token_expiry)
            if 'refresh_expireTime' in data:
                self._refresh_expiry = dt.datetime.fromtimestamp(float(data['refresh_expireTime'])/1000)
                _LOGGER.debug('Got refresh expiry: %s', self._refresh_expiry)
            return self._access_token
        return None

    async def request(self, path, payload=None, retry=2):
        """Request data."""
        # pylint: disable=too-many-return-statements

        _LOGGER.debug(payload)

        url = API_ENDPOINT + path
        headers = {
                   'access_token': await self.token()
        }
        try:
            with async_timeout.timeout(self._timeout):
                resp = await self.websession.post(url,
                                                  headers=headers,
                                                  params=payload)
        except (asyncio.TimeoutError, aiohttp.ClientError) as err:
            _LOGGER.error("Error sending command to Mill: %s, %s", command, err)
            return None


        body = await resp.json()
        if 'errorCode' in body:
            if body['errorCode'] == 101:
                _LOGGER.error("Remote system error")
                return None
            if body['errorCode'] == 102:
                _LOGGER.error("UDS error")
                return None
            if body['errorCode'] == 303:
                _LOGGER.error("The device is not yours")
                return None
            if body['errorCode'] == 304:
                _LOGGER.error("Cannot find device info")
                return None
        return body['data']

    async def get_home_list(self):
        """Request data."""
        resp = await self.request("/uds/selectHomeList")
        if resp is None:
            return None
        homes = resp.get('homeList')
        return homes

    async def update_rooms(self):
        """Request data."""
        homes = await self.get_home_list()
        if homes is None:
            return None
        for home in homes:
            payload = {"homeId": home.get("homeId")}
            data = await self.request("/uds/selectRoombyHome", payload)
            rooms = data.get('roomList', [])
            if not rooms:
                continue
            for _room in rooms:
                _id = _room.get('roomId')
                room = self.rooms.get(_id, Room())
                room.room_id = _id
                room.comfort_temp = _room.get("comfortTemp")
                room.away_temp = _room.get("awayTemp")
                room.sleep_temp = _room.get("sleepTemp")
                room.name = _room.get("roomName")
                room.current_mode = _room.get("currentMode")
                room.heat_status = _room.get("heatStatus")

                self.rooms[_id] = room

    def sync_update_rooms(self):
        """Request data."""
        loop = asyncio.get_event_loop()
        task = loop.create_task(self.update_rooms())
        loop.run_until_complete(task)

    # async def set_room_temperatures(self, room_id, sleep_temp=None,
    #                                 comfort_temp=None, away_temp=None):
    #     """Set room temps."""
    #     room = self.rooms.get(room_id)
    #     if room is None:
    #         _LOGGER.error("No such device")
    #         return
    #     if sleep_temp is None:
    #         sleep_temp = room.sleep_temp
    #     if away_temp is None:
    #         away_temp = room.away_temp
    #     if comfort_temp is None:
    #         comfort_temp = room.comfort_temp
    #     payload = {"roomId": room_id,
    #                "sleepTemp": sleep_temp,
    #                "comfortTemp": comfort_temp,
    #                "awayTemp": away_temp,
    #                "homeType": 0}
    #     await self.request("/changeRoomModeTempInfo", payload)

    # def sync_set_room_temperatures(self, room_id, sleep_temp=None,
    #                                comfort_temp=None, away_temp=None):
    #     """Set heater temps."""
    #     loop = asyncio.get_event_loop()
    #     task = loop.create_task(self.set_room_temperatures(room_id,
    #                                                        sleep_temp,
    #                                                        comfort_temp,
    #                                                        away_temp))
    #     loop.run_until_complete(task)

    async def update_heaters(self):
        """Request data."""
        homes = await self.get_home_list()
        heaters = []
        if homes is None:
            return None
        for home in homes:
            payload = {"homeId": home.get("homeId")}
            data = await self.request("/uds/getIndependentDevices", payload)
            heaters.extend(data.get('deviceInfoList', []))
        for room in self.rooms.keys():
            payload = {"roomId": room}
            data = await self.request("/uds/selectDevicebyRoom", payload)
            heaters.extend(data.get('deviceList', []))
        if heaters:
            for _heater in heaters:
                if not _heater:
                    continue
                _id = _heater.get('deviceId')
                heater = self.heaters.get(_id, Heater())
                heater.device_id = _id
                heater.current_temp = _heater.get('currentTemp')
                heater.device_status = _heater.get('deviceStatus')
                heater.name = _heater.get('deviceName')
                heater.flag = _heater.get('heaterFlag')
                heater.control_type = _heater.get('controlType')
                heater.can_change_temp = _heater.get('canChangeTemp')
                #heater.fan_status = _heater.get('fanStatus')
                #heater.set_temp = _heater.get('holidayTemp')
                #heater.power_status = _heater.get('powerStatus')

                self.heaters[_id] = heater

    def sync_update_heaters(self):
        """Request data."""
        loop = asyncio.get_event_loop()
        task = loop.create_task(self.update_heaters())
        loop.run_until_complete(task)

    async def throttle_update_heaters(self):
        """Throttle update device."""
        if (self._throttle_time is not None
                and dt.datetime.now() - self._throttle_time < MIN_TIME_BETWEEN_UPDATES):
            return
        self._throttle_time = dt.datetime.now()
        await self.update_heaters()

    async def update_device(self, device_id):
        """Update device."""
        await self.throttle_update_heaters()
        return self.heaters.get(device_id)

    # async def heater_control(self, device_id, fan_status=None,
    #                          power_status=None):
    #     """Set heater temps."""
    #     heater = self.heaters.get(device_id)
    #     if heater is None:
    #         _LOGGER.error("No such device")
    #         return
    #     if fan_status is None:
    #         fan_status = heater.fan_status
    #     if power_status is None:
    #         power_status = heater.power_status
    #     operation = 0 if fan_status == heater.fan_status else 4
    #     payload = {"subDomain": 5332,
    #                "deviceId": device_id,
    #                "testStatus": 1,
    #                "operation": operation,
    #                "status": power_status,
    #                "windStatus": fan_status,
    #                "holdTemp": heater.set_temp,
    #                "tempType": 0,
    #                "powerLevel": 0}
    #     await self.request("/uds/deviceControlForOpenApi", payload)

    # def sync_heater_control(self, device_id, fan_status=None,
    #                         power_status=None):
    #     """Set heater temps."""
    #     loop = asyncio.get_event_loop()
    #     task = loop.create_task(self.heater_control(device_id,
    #                                                 fan_status,
    #                                                 power_status))
    #     loop.run_until_complete(task)

    async def set_heater_temp(self, device_id, set_temp):
        """Set heater temp."""
        payload = {"deviceId": device_id,
                   "holdTemp": int(set_temp),
                   "operation": 1}
        await self.request("/uds/deviceControlForOpenApi", payload)

    def sync_set_heater_temp(self, device_id, set_temp):
        """Set heater temps."""
        loop = asyncio.get_event_loop()
        task = loop.create_task(self.set_heater_temp(device_id, set_temp))
        loop.run_until_complete(task)


class Room:
    """Representation of room."""
    # pylint: disable=too-few-public-methods

    room_id = None
    comfort_temp = None
    away_temp = None
    sleep_temp = None
    name = None
    is_offline = None
    heat_status = None


class Heater:
    """Representation of heater."""
    # pylint: disable=too-few-public-methods

    device_id = None
    current_temp = None
    name = None
    set_temp = None
    fan_status = None
    power_status = None
