""" Python Code for Communication with the Ecobee Thermostat """
from typing import Optional

import requests
from requests.exceptions import HTTPError, RequestException, Timeout

try:
    import simplejson as json
except ImportError:
    import json

from .const import (
    _LOGGER,
    ECOBEE_ACCESS_TOKEN,
    ECOBEE_API_KEY,
    ECOBEE_API_VERSION,
    ECOBEE_AUTHORIZATION_CODE,
    ECOBEE_BASE_URL,
    ECOBEE_CONFIG_FILENAME,
    ECOBEE_DEFAULT_TIMEOUT,
    ECOBEE_ENDPOINT_AUTH,
    ECOBEE_ENDPOINT_THERMOSTAT,
    ECOBEE_ENDPOINT_RUNTIMEREPORT,
    ECOBEE_ENDPOINT_TOKEN,
    ECOBEE_REFRESH_TOKEN,
    ECOBEE_OPTIONS_NOTIFICATIONS,
)
from .errors import ExpiredTokenError, InvalidTokenError
from .util import config_from_file, convert_to_bool


class Ecobee(object):
    """Class for communicating with the ecobee API."""

    def __init__(self, config_filename: str = None, config: dict = None):
        self.thermostats = None
        self.config_filename = config_filename
        self.config = config
        self.api_key = None
        self.pin = None
        self.authorization_code = None
        self.access_token = None
        self.refresh_token = None
        self.include_notifications = False

        if self.config_filename is None and self.config is None:
            _LOGGER.error("No ecobee credentials supplied, unable to continue")
            return

        if self.config:
            self._file_based_config = False
            self.api_key = self.config[ECOBEE_API_KEY]
            if ECOBEE_ACCESS_TOKEN in self.config:
                self.access_token = self.config[ECOBEE_ACCESS_TOKEN]
            if ECOBEE_AUTHORIZATION_CODE in self.config:
                self.authorization_code = self.config[ECOBEE_AUTHORIZATION_CODE]
            if ECOBEE_REFRESH_TOKEN in self.config:
                self.refresh_token = self.config[ECOBEE_REFRESH_TOKEN]
            if ECOBEE_OPTIONS_NOTIFICATIONS in self.config:
                self.include_notifications = convert_to_bool(self.config[ECOBEE_OPTIONS_NOTIFICATIONS])
        else:
            self._file_based_config = True

    def read_config_from_file(self) -> None:
        """Reads config info from passed-in config filename."""
        if self._file_based_config:
            self.config = config_from_file(self.config_filename)
            self.api_key = self.config[ECOBEE_API_KEY]
            if ECOBEE_ACCESS_TOKEN in self.config:
                self.access_token = self.config[ECOBEE_ACCESS_TOKEN]
            if ECOBEE_AUTHORIZATION_CODE in self.config:
                self.authorization_code = self.config[ECOBEE_AUTHORIZATION_CODE]
            if ECOBEE_REFRESH_TOKEN in self.config:
                self.refresh_token = self.config[ECOBEE_REFRESH_TOKEN]
            if ECOBEE_OPTIONS_NOTIFICATIONS in self.config:
                self.include_notifications = convert_to_bool(self.config[ECOBEE_OPTIONS_NOTIFICATIONS])

    def _write_config(self) -> None:
        """Writes API tokens to a file or self.config if self.file_based_config is False."""
        config = dict()
        config[ECOBEE_API_KEY] = self.api_key
        config[ECOBEE_ACCESS_TOKEN] = self.access_token
        config[ECOBEE_REFRESH_TOKEN] = self.refresh_token
        config[ECOBEE_AUTHORIZATION_CODE] = self.authorization_code
        config[ECOBEE_OPTIONS_NOTIFICATIONS] = str(self.include_notifications)
        if self._file_based_config:
            config_from_file(self.config_filename, config)
        else:
            self.config = config

    def request_pin(self) -> bool:
        """Requests a PIN from ecobee for authorization on ecobee.com."""
        params = {
            "response_type": "ecobeePin",
            "client_id": self.api_key,
            "scope": "smartWrite",
        }
        log_msg_action = "request pin"

        response = self._request(
            "GET",
            ECOBEE_ENDPOINT_AUTH,
            log_msg_action,
            params=params,
            auth_request=True,
        )

        try:
            self.authorization_code = response["code"]
            self.pin = response["ecobeePin"]
            _LOGGER.debug(
                f"Authorize your ecobee developer app with PIN code {self.pin}. "
                f"Goto https://www.ecobee/com/consumerportal/index.html, "
                f"Click My Apps, Add Application, Enter Pin and click Authorize. "
                f"After authorizing, call request_tokens method."
            )
            return True
        except (KeyError, TypeError) as err:
            _LOGGER.debug(f"Error obtaining PIN code from ecobee: {err}")
            return False

    def request_tokens(self) -> bool:
        """Requests API tokens from ecobee."""
        params = {
            "grant_type": "ecobeePin",
            "code": self.authorization_code,
            "client_id": self.api_key,
        }
        log_msg_action = "request tokens"

        response = self._request(
            "POST",
            ECOBEE_ENDPOINT_TOKEN,
            log_msg_action,
            params=params,
            auth_request=True,
        )

        try:
            self.access_token = response["access_token"]
            self.refresh_token = response["refresh_token"]
            self._write_config()
            self.pin = None
            _LOGGER.debug(f"Obtained tokens from ecobee: access {self.access_token}, "
                          f"refresh {self.refresh_token}")
            return True
        except (KeyError, TypeError) as err:
            _LOGGER.debug(f"Error obtaining tokens from ecobee: {err}")
            return False

    def refresh_tokens(self) -> bool:
        """Refreshes ecobee API tokens."""
        params = {
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
            "client_id": self.api_key,
        }
        log_msg_action = "refresh tokens"

        response = self._request(
            "POST",
            ECOBEE_ENDPOINT_TOKEN,
            log_msg_action,
            params=params,
            auth_request=True,
        )

        try:
            self.access_token = response["access_token"]
            self.refresh_token = response["refresh_token"]
            self._write_config()
            _LOGGER.debug(f"Refreshed tokens from ecobee: access {self.access_token}, "
                          f"refresh {self.refresh_token}")
            return True
        except (KeyError, TypeError) as err:
            _LOGGER.debug(f"Error refreshing tokens from ecobee: {err}")
            return False

    def get_thermostats(self) -> bool:
        """Gets a json-list of thermostats from ecobee and caches in self.thermostats."""
        param_string = {
            "selection": {
                "selectionType": "registered",
                "includeRuntime": "true",
                "includeSensors": "true",
                "includeProgram": "true",
                "includeEquipmentStatus": "true",
                "includeEvents": "true",
                "includeWeather": "true",
                "includeSettings": "true",
            }
        }
        if self.include_notifications:
            param_string["selection"]["includeNotificationSettings"] = self.include_notifications
        params = {"json": json.dumps(param_string)}
        log_msg_action = "get thermostats"

        response = self._request(
            "GET", ECOBEE_ENDPOINT_THERMOSTAT, log_msg_action, params=params
        )

        try:
            self.thermostats = response["thermostatList"]
            return True
        except (KeyError, TypeError):
            return False

    def get_thermostat(self, index: int) -> str:
        """Returns a single thermostat based on list index of self.thermostats."""
        return self.thermostats[index]

    def get_remote_sensors(self, index: int) -> str:
        """Returns remote sensors from a thermostat based on list index of self.thermostats."""
        return self.thermostats[index]["remoteSensors"]
    
    def get_equipment_notifications(self, index: int) -> str:
        """Returns equipment notifications from a thermostat based on list index of self.thermostats."""
        return self.thermostats[index]["notificationSettings"]["equipment"]

    def update(self) -> bool:
        """Gets new thermostat data from ecobee; wrapper for get_thermostats."""
        return self.get_thermostats()
    
    def getExtThermostats(self) -> bool:
        #print(dt.datetime.now(), 'getExtThermostats')
        """Gets a json-list of thermostats from ecobee and caches in self.thermostats."""
        param_string = {
            "selection": {
                "selectionType": "registered",
                "includeExtendedRuntime": "true",
            }
        }
        params = {"json": json.dumps(param_string)}
        log_msg_action = "get extended thermostats"

        response = self._request(
            "GET", ECOBEE_ENDPOINT_THERMOSTAT, log_msg_action, params=params
        )

        try:
            self.thermostatsExt = response["thermostatList"]
            return True
        except (KeyError, TypeError):
            return False
        
    def set_hvac_mode(self, index: int, hvac_mode: str) -> None:
        """Sets the HVAC mode (auto, auxHeatOnly, cool, heat, off)."""
        body = {
            "selection": {
                "selectionType": "thermostats",
                "selectionMatch": self.thermostats[index]["identifier"],
            },
            "thermostat": {"settings": {"hvacMode": hvac_mode}},
        }
        log_msg_action = "set HVAC mode"

        try:
            self._request("POST", ECOBEE_ENDPOINT_THERMOSTAT, log_msg_action, body=body)
        except (ExpiredTokenError, InvalidTokenError) as err:
            raise err

    def set_fan_min_on_time(self, index: int, fan_min_on_time: int) -> None:
        """Sets the minimum time, in minutes, to run the fan each hour (1 to 60)."""
        body = {
            "selection": {
                "selectionType": "thermostats",
                "selectionMatch": self.thermostats[index]["identifier"],
            },
            "thermostat": {"settings": {"fanMinOnTime": fan_min_on_time}},
        }
        log_msg_action = "set fan minimum on time"

        try:
            self._request("POST", ECOBEE_ENDPOINT_THERMOSTAT, log_msg_action, body=body)
        except (ExpiredTokenError, InvalidTokenError) as err:
            raise err

    def set_fan_mode(
        self,
        index: int,
        fan_mode: str,
        cool_temp: int,
        heat_temp: int,
        hold_type: str = "nextTransition",
    ) -> None:
        """Sets the fan mode (auto, minontime, on)."""
        body = {
            "selection": {
                "selectionType": "thermostats",
                "selectionMatch": self.thermostats[index]["identifier"],
            },
            "functions": [
                {
                    "type": "setHold",
                    "params": {
                        "holdType": hold_type,
                        "coolHoldTemp": int(cool_temp * 10),
                        "heatHoldTemp": int(heat_temp * 10),
                        "fan": fan_mode,
                    },
                }
            ],
        }
        log_msg_action = "set fan mode"

        try:
            self._request("POST", ECOBEE_ENDPOINT_THERMOSTAT, log_msg_action, body=body)
        except (ExpiredTokenError, InvalidTokenError) as err:
            raise err

    def set_hold_temp(
        self,
        index: int,
        cool_temp: int,
        heat_temp: int,
        hold_type: str = "nextTransition",
        hold_hours: str = "2",
    ) -> None:
        """Sets a hold temperature."""
        if hold_type == "holdHours":
            body = {
                "selection": {
                    "selectionType": "thermostats",
                    "selectionMatch": self.thermostats[index]["identifier"],
                },
                "functions": [
                    {
                        "type": "setHold",
                        "params": {
                            "holdType": hold_type,
                            "coolHoldTemp": int(cool_temp * 10),
                            "heatHoldTemp": int(heat_temp * 10),
                            "holdHours": hold_hours,
                        },
                    }
                ],
            }
        else:
            body = {
                "selection": {
                    "selectionType": "thermostats",
                    "selectionMatch": self.thermostats[index]["identifier"],
                },
                "functions": [
                    {
                        "type": "setHold",
                        "params": {
                            "holdType": hold_type,
                            "coolHoldTemp": int(cool_temp * 10),
                            "heatHoldTemp": int(heat_temp * 10),
                        },
                    }
                ],
            }
        log_msg_action = "set hold temp"

        try:
            self._request("POST", ECOBEE_ENDPOINT_THERMOSTAT, log_msg_action, body=body)
        except (ExpiredTokenError, InvalidTokenError) as err:
            raise err

    def set_climate_hold(
        self, index: int, climate: str, hold_type: str = "nextTransition", hold_hours: int = None
    ) -> None:
        """Sets a climate hold (away, home, sleep)."""
        body = {
            "selection": {
                "selectionType": "thermostats",
                "selectionMatch": self.thermostats[index]["identifier"],
            },
            "functions": [
                {
                    "type": "setHold",
                    "params": {"holdType": hold_type, "holdClimateRef": climate, "holdHours": hold_hours},
                }
            ],
        }

        if hold_type != "holdHours":
            del body["functions"][0]["params"]["holdHours"]

        log_msg_action = "set climate hold"

        try:
            self._request("POST", ECOBEE_ENDPOINT_THERMOSTAT, log_msg_action, body=body)
        except (ExpiredTokenError, InvalidTokenError) as err:
            raise err
        
    def Set_Climate_hold(
            self,
            climate: str,
            hold_type: str = "nextTransition",
            index:      int = None,
            hold_hours: int = None,
            start_date: str = None,
            start_time: str = None,
            end_date:   str = None,
            end_time:   str = None,
    ) -> None:
        """Sets a climate hold (away, home, sleep)."""
        body = {
            "selection": {
                "selectionType": "registered",
                "selectionMatch": "",
            },
            "functions": [
                {
                    "type": "setHold",
                    "params": {"holdType": hold_type,
                               "holdClimateRef": climate,
                               "holdHours": hold_hours,
                               "startDate": start_date,
                               "startTime": start_time,
                               "endDate":   end_date,
                               "endTime":   end_time
                               },
                }
            ],
        }

        if hold_type != "holdHours":
            del body["functions"][0]["params"]["holdHours"]

        if hold_type != "dateTime":
            for option in ["start_date", "start_time", "end_date", "end_time"]:
                del body["functions"][0]["params"][option]

        if index is not None:
            del body["selection"]
            body["selection"] = {
                "selectionType": "thermostats",
                "selectionMatch": self.thermostats[index]["identifier"],
                }

        log_msg_action = "set climate hold"
        #
        try:
            self._request("POST", ECOBEE_ENDPOINT_THERMOSTAT, log_msg_action, body=body)
        except (ExpiredTokenError, InvalidTokenError) as err:
            raise err
        
    def create_vacation(
        self,
        index: int,
        vacation_name: str,
        cool_temp: int,
        heat_temp: int,
        start_date: str = None,
        start_time: str = None,
        end_date: str = None,
        end_time: str = None,
        fan_mode: str = "auto",
        fan_min_on_time: str = "0",
    ) -> None:
        """Creates a vacation."""
        body = {
            "selection": {
                "selectionType": "thermostats",
                "selectionMatch": self.thermostats[index]["identifier"],
            },
            "functions": [
                {
                    "type": "createVacation",
                    "params": {
                        "name": vacation_name,
                        "coolHoldTemp": int(cool_temp * 10),
                        "heatHoldTemp": int(heat_temp * 10),
                        "startDate": start_date,
                        "startTime": start_time,
                        "endDate": end_date,
                        "endTime": end_time,
                        "fan": fan_mode,
                        "fanMinOnTime": fan_min_on_time,
                    },
                }
            ],
        }
        log_msg_action = "create a vacation"

        try:
            self._request("POST", ECOBEE_ENDPOINT_THERMOSTAT, log_msg_action, body=body)
        except (ExpiredTokenError, InvalidTokenError) as err:
            raise err

    def Create_vacation(
        self,
        index: int,
        vacation_name: str,
        cool_temp: int,
        heat_temp: int,
        start_date: str = None,
        start_time: str = None,
        end_date: str = None,
        end_time: str = None,
        fan_mode: str = "auto",
        fan_min_on_time: str = "0",
    ) -> None:
        """Creates a vacation on all registered"""
        body = {
            "selection": {
                "selectionType": "registered",
                "selectionMatch": "",
            },
            "functions": [
                {
                    "type": "createVacation",
                    "params": {
                        "name": vacation_name,
                        "coolHoldTemp": int(cool_temp * 10),
                        "heatHoldTemp": int(heat_temp * 10),
                        "startDate": start_date,
                        "startTime": start_time,
                        "endDate": end_date,
                        "endTime": end_time,
                        "fan": fan_mode,
                        "fanMinOnTime": fan_min_on_time,
                    },
                }
            ],
        }
        log_msg_action = "create a vacation"

        try:
            self._request("POST", ECOBEE_ENDPOINT_THERMOSTAT, log_msg_action, body=body)
        except (ExpiredTokenError, InvalidTokenError) as err:
            raise err
        
    def delete_vacation(self, index: int, vacation: str) -> None:
        """Deletes a vacation."""
        body = {
            "selection": {
                "selectionType": "thermostats",
                "selectionMatch": self.thermostats[index]["identifier"],
            },
            "functions": [{"type": "deleteVacation", "params": {"name": vacation}}],
        }
        log_msg_action = "delete a vacation"

        try:
            self._request("POST", ECOBEE_ENDPOINT_THERMOSTAT, log_msg_action, body=body)
        except (ExpiredTokenError, InvalidTokenError) as err:
            raise err

    def Delete_vacation(self, index: int, vacation: str) -> None:
        """Deletes a vacation on all registered."""
        body = {
            "selection": {
                "selectionType": "registered",
                "selectionMatch": "",
            },
            "functions": [{"type": "deleteVacation", "params": {"name": vacation}}],
        }
        log_msg_action = "delete a vacation"

        try:
            self._request("POST", ECOBEE_ENDPOINT_THERMOSTAT, log_msg_action, body=body)
        except (ExpiredTokenError, InvalidTokenError) as err:
            raise err


    def resume_program(self, index: int, resume_all: bool = False) -> None:
        """Resumes the currently scheduled program."""
        body = {
            "selection": {
                "selectionType": "thermostats",
                "selectionMatch": self.thermostats[index]["identifier"],
            },
            "functions": [
                {"type": "resumeProgram", "params": {"resumeAll": resume_all}}
            ],
        }
        log_msg_action = "resume program"

        try:
            self._request("POST", ECOBEE_ENDPOINT_THERMOSTAT, log_msg_action, body=body)
        except (ExpiredTokenError, InvalidTokenError) as err:
            raise err

    def send_message(self, index: int, message: str = None) -> None:
        """Sends the first 500 characters of a message to the thermostat."""
        if message is None:
            message = "Hello from pyecobee!"

        body = {
            "selection": {
                "selectionType": "thermostats",
                "selectionMatch": self.thermostats[index]["identifier"],
            },
            "functions": [{"type": "sendMessage", "params": {"text": message[0:500]}}],
        }
        log_msg_action = "send message"

        try:
            self._request("POST", ECOBEE_ENDPOINT_THERMOSTAT, log_msg_action, body=body)
        except (ExpiredTokenError, InvalidTokenError) as err:
            raise err

    def set_humidifier_mode(self, index: int, humidifier_mode: str) -> None:
        """Sets the humidifier mode (auto, off, manual)."""
        body = {
            "selection": {
                "selectionType": "thermostats",
                "selectionMatch": self.thermostats[index]["identifier"],
            },
            "thermostat": {"settings": {"humidifierMode": humidifier_mode}},
        }
        log_msg_action = "set humidifier mode"

        try:
            self._request("POST", ECOBEE_ENDPOINT_THERMOSTAT, log_msg_action, body=body)
        except (ExpiredTokenError, InvalidTokenError) as err:
            raise err

    def set_humidity(self, index: int, humidity: str) -> None:
        """Sets target humidity level."""
        body = {
            "selection": {
                "selectionType": "thermostats",
                "selectionMatch": self.thermostats[index]["identifier"],
            },
            "thermostat": {"settings": {"humidity": str(humidity)}},
        }
        log_msg_action = "set humidity level"

        try:
            self._request("POST", ECOBEE_ENDPOINT_THERMOSTAT, log_msg_action, body=body)
        except (ExpiredTokenError, InvalidTokenError) as err:
            raise err

    def set_mic_mode(self, index: int, mic_enabled: bool) -> None:
        """Enables/Disables Alexa microphone (only for ecobee4)."""
        body = {
            "selection": {
                "selectionType": "thermostats",
                "selectionMatch": self.thermostats[index]["identifier"],
            },
            "thermostat": {"audio": {"microphoneEnabled": mic_enabled}},
        }
        log_msg_action = "set mic mode"

        try:
            self._request("POST", ECOBEE_ENDPOINT_THERMOSTAT, log_msg_action, body=body)
        except (ExpiredTokenError, InvalidTokenError) as err:
            raise err

    def set_occupancy_modes(
        self, index: int, auto_away: bool = None, follow_me: bool = None
    ) -> None:
        """Enables/Disables Smart Home/Away and Follow Me modes."""
        body = {
            "selection": {
                "selectionType": "thermostats",
                "selectionMatch": self.thermostats[index]["identifier"],
            },
            "thermostat": {
                "settings": {"autoAway": auto_away, "followMeComfort": follow_me}
            },
        }
        log_msg_action = "set occupancy modes"

        try:
            self._request("POST", ECOBEE_ENDPOINT_THERMOSTAT, log_msg_action, body=body)
        except (ExpiredTokenError, InvalidTokenError) as err:
            raise err

    def set_dst_mode(self, index: int, enable_dst: bool) -> None:
        """Enables/Disables daylight savings time."""
        body = {
            "selection": {
                "selectionType": "thermostats",
                "selectionMatch": self.thermostats[index]["identifier"],
            },
            "thermostat": {"location": {"isDaylightSaving": enable_dst}},
        }
        log_msg_action = "set dst mode"

        try:
            self._request("POST", ECOBEE_ENDPOINT_THERMOSTAT, log_msg_action, body=body)
        except (ExpiredTokenError, InvalidTokenError) as err:
            raise err

    def RuntimeReport(self, index: int, startDate: str, endDate: str,
                      startInverval: int = 0, endInterval: int = 287,
                      columns: str = None) -> None:
        allColumns = "auxHeat1,auxHeat2,auxHeat3,compCool1,compCool2,"     +\
            "compHeat1,compHeat2,dehumidifier,dmOffset,economizer,"        +\
            "fan,humidifier,hvacMode,outdoorHumidity,outdoorTemp,"         +\
            "sky,ventilator,wind,zoneAveTemp,zoneCalendarEvent,"           +\
            "zoneClimate,zoneCoolTemp,zoneHeatTemp,zoneHumidity,"          +\
            "zoneHumidityHigh,zoneHumidityLow,zoneHvacMode,zoneOccupancy"
        defaultColumns = "auxHeat1,auxHeat2,auxHeat3,compCool1,compCool2," +\
            "fan,hvacMode,outdoorHumidity,outdoorTemp,sky,wind,"           +\
            "zoneAveTemp,zone,CalendarEvent,zoneClimate,zoneCoolTemp,"      +\
            "zoneHeatTemp,zoneHumidity,zoneHumidityHigh,zoneHumidityLow,"  +\
            "zoneHvacMode"
        defaultColumns = "zoneAveTemp,zoneHumidity,outdoorTemp,outdoorHumidity"
        if columns is None:
            columns = defaultColumns
        
        body = {
            "selection": {
                "selectionType": "thermostats",
                "selectionMatch": self.thermostats[index]["identifier"],
            },
            "startDate":startDate,
            "endDate":endDate,
            "startInverval":startInverval,
            "endInterval":endInterval,
            "columns":columns,
        }
        #if self.include_notifications:
        #    body["selection"]["includeNotificationSettings"] = self.include_notifications
        #body = {"json": json.dumps(body)}
        body = json.dumps(body)
        log_msg_action = "runtimeReport"

        if True:
            print('\nruntimeReport:index:', index, 'start:', startDate, 'end:', endDate)
            print('\nruntimeReport:interval:', startInverval, endInterval)
            print('\nruntimeReport:columns:', columns)
            print('\nnuntimeReport:body:', body)
            print('\n')
            
        response = self._request(
            "GET", ECOBEE_ENDPOINT_RUNTIMEREPORT + "?format=json&body=", log_msg_action, body=body
        )
        print(response)
        try:
            self.runtimeReport = response["thermostatList"]
            return True
        except (KeyError, TypeError):
            return False

    def runtimeReport(self, thermostats, startDate: str, endDate: str,
                      startInverval: int = 0, endInterval: int = 287,
                      columns: str = None) -> None:
        allColumns = "auxHeat1,auxHeat2,auxHeat3,compCool1,compCool2,"     +\
            "compHeat1,compHeat2,dehumidifier,dmOffset,economizer,"        +\
            "fan,humidifier,hvacMode,outdoorHumidity,outdoorTemp,"         +\
            "sky,ventilator,wind,zoneAveTemp,zoneCalendarEvent,"           +\
            "zoneClimate,zoneCoolTemp,zoneHeatTemp,zoneHumidity,"          +\
            "zoneHumidityHigh,zoneHumidityLow,zoneHvacMode,zoneOccupancy"
        defaultColumns = "auxHeat1,auxHeat2,auxHeat3,compCool1,compCool2," +\
            "fan,hvacMode,outdoorHumidity,outdoorTemp,sky,wind,"           +\
            "zoneAveTemp,zone,CalendarEvent,zoneClimate,zoneCoolTemp,"      +\
            "zoneHeatTemp,zoneHumidity,zoneHumidityHigh,zoneHumidityLow,"  +\
            "zoneHvacMode"
        defaultColumns = "zoneAveTemp,zoneHumidity,outdoorTemp,outdoorHumidity"
        if columns is None:
            columns = defaultColumns

        thermoNames = ''
        for index in thermostats:
            thermoNames +=  self.thermostats[index]["identifier"]+ ','
        thermoNames = thermoNames[0 : (len(thermoNames) - 1)]
        payload = {
            "selection": {
                "selectionType": "thermostats",
                "selectionMatch": thermoNames,
            },
            "startDate":startDate,         "endDate":endDate,
            "startInverval":startInverval, "endInterval":endInterval,
            "columns":columns,
        }
        payload = json.dumps(payload)
        log_msg_action = "runtimeReport"
        
        if False:
            print('\nruntimeReport:index:', index, 'start:', startDate, 'end:', endDate)
            print('\nruntimeReport:interval:', startInverval, endInterval)
            print('\nruntimeReport:columns:', columns)
            print('\nnuntimeReport:payload:', payload)
            print('\n')
            
        response = self._request(
            "GET", ECOBEE_ENDPOINT_RUNTIMEREPORT + "?format=json&body=", log_msg_action,
            payload=payload
        )
        #print('response:',response)
        #print('response.rowlist:', response["rowList"])
        #return response['reportList'][0]
        try:
            self.runtimeReportData = response['reportList']
            return True
        except (KeyError, TypeError):
            return False

    def _request(
        self,
        method: str,
        endpoint: str,
        log_msg_action: str,
        params: dict = None,
        body: dict = None,
        payload: str = None,
        auth_request: bool = False,
        retrying: bool = False
    ) -> Optional[str]:
        """Makes a request to the ecobee API."""
        url = f"{ECOBEE_BASE_URL}/{endpoint}"
        headers = dict()

        if not auth_request:
            url = f"{ECOBEE_BASE_URL}/{ECOBEE_API_VERSION}/{endpoint}"
            if payload is not None:
                #print('payload:', payload, 'url:', url)
                url = url + payload
            headers = {
                "Content-Type": "application/json;charset=UTF-8",
                "Authorization": f"Bearer {self.access_token}",
            }

        _LOGGER.debug(
            f"Making request to {endpoint} endpoint to {log_msg_action}: "
            f"url: {url}, headers: {headers}, params: {params}, body: {body}"
        )

        try:
            response = requests.request(
                method, url, headers=headers, params=params, json=body, timeout=ECOBEE_DEFAULT_TIMEOUT
            )

            try:
                log_msg = response.json()
            except:
                log_msg = response.text
            _LOGGER.debug(
                f"Request response: {response.status_code}: {log_msg}"
            )
            
            response.raise_for_status()
            return response.json()
        except HTTPError:
            json_payload = {}
            try:
                json_payload = response.json()
            except json.decoder.JSONDecodeError:
                _LOGGER.debug("Invalid JSON payload received")

            if auth_request:
                if (
                    response.status_code == 400
                    and json_payload.get("error") == "invalid_grant"
                ):
                    raise InvalidTokenError(
                        "ecobee tokens invalid; re-authentication required"
                    )
                else:
                    _LOGGER.error(
                        f"Error requesting authorization from ecobee: "
                        f"{response.status_code}: {json_payload}"
                    )
            elif response.status_code == 500:
                code = json_payload.get("status", {}).get("code")
                if code in [1, 16]:
                    raise InvalidTokenError(
                        "ecobee tokens invalid; re-authentication required"
                    )
                elif code == 14:
                    if retrying:
                        raise ExpiredTokenError(
                            "ecobee access token expired; token refresh required"
                        )
                    else:
                        #print('retrying from _request')
                        rc = self.refresh_tokens()
                        #print('_request: refresh_tokens returned:', rc)
                        self._write_config()
                        #print('_request: called ._write_config()')
                        _LOGGER.warning(
                            f"Attempting retry for ExpiredTokenError "
                            f"While attempting to {log_msg_action}: "
                            f"method: {method}: endpoint: {endpoint}: "
                            f"params: {params}: body: {body}: "
                            f"auth_request: {auth_request}: retrying: {retrying}: "
                            )
                        response = self._request(
                            method,
                            endpoint,
                            log_msg_action,
                            params,
                            body,
                            payload,
                            auth_request,
                            retrying = True
                        )
                        # responce is responce.json() at this point
                        return response
                else:
                    _LOGGER.error(
                        f"Error from ecobee while attempting to {log_msg_action}: "
                        f"{code}: {json_payload.get('status', {}).get('message', 'Unknown error')}"
                    )
            else:
                _LOGGER.error(
                    f"Error from ecobee while attempting to {log_msg_action}: "
                    f"{response.status_code}: {json_payload}"
                )
        except Timeout:
            _LOGGER.error(
                f"Connection to ecobee timed out while attempting to {log_msg_action}. "
                f"Possible connectivity outage."
            )
        except (RequestException, json.decoder.JSONDecodeError):
            _LOGGER.error(
                f"Error connecting to ecobee while attempting to {log_msg_action}. "
                f"Possible connectivity outage."
            )
        return None
