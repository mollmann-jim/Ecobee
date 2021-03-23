#!/usr/bin/env python3
#from html.parser import HTMLParser
import requests
import datetime as dt
import sqlite3
from dateutil.tz import tz
import pprint
import json
from sys import path
path.append('/home/jim/tools/Ecobee/')
import pyecobee
import logging
import time
import os
import sys
from traceback import print_exc
from pyecobee.const import (
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
    ECOBEE_ENDPOINT_TOKEN,
    ECOBEE_REFRESH_TOKEN,
    ECOBEE_OPTIONS_NOTIFICATIONS,
)

def setLogging(logger):
    logger.setLevel(logging.DEBUG)
    # create file handler which logs even debug messages
    fh = logging.FileHandler('ecobee.log')
    fh.setLevel(logging.ERROR)
    fh.setLevel(logging.WARNING)
    # create console handler with a higher log level
    ch = logging.StreamHandler()
    ch.setLevel(logging.ERROR)
    # create formatter and add it to the handlers
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)
    # add the handlers to the logger
    logger.addHandler(fh)
    logger.addHandler(ch)

def findSubstr(s1, s2):
    l = s1.split(',')
    for i in range(len(l)):
        if l[i].lower().find(s2) != -1:
            return l[i]
    return None

class saveEcobeeData():
    def __init__(self):
        self.prevStatusTime = [0, 0]
        DBname = '/home/jim/tools/Ecobee/MBthermostat.sched.sql'
        self.DB = sqlite3.connect(DBname)
        self.DB.row_factory = sqlite3.Row
        self.c = {}
        self.initDB()
        self.prevWeather = 0
        self.pp = pprint.PrettyPrinter(indent=4, sort_dicts=False)
        
    def initDB(self):
        for table in ['Upstairs', 'Downstairs']:
            self.c[table] = self.DB.cursor()
            #drop = 'DROP TABLE IF EXISTS ' + table + ';'
            #c[table].execute(drop)
            create = 'CREATE TABLE IF NOT EXISTS ' + table + '( \n' +\
                ' id             INTEGER PRIMARY KEY, \n' +\
                ' timestamp      INTEGER DEFAULT CURRENT_TIMESTAMP, \n' +\
                ' statusTime     INTEGER, \n' +\
                ' temp           REAL,    \n' +\
                ' humidity       INTEGER, \n' +\
                ' coolSetPoint   REAL,    \n' +\
                ' heatSetPoint   REAL,    \n' +\
                ' coolStatus     TEXT,    \n' +\
                ' heatStatus     TEXT,    \n' +\
                ' fanStatus      TEXT,    \n' +\
                ' fanOn          TEXT,    \n' +\
                ' hvacMode       TEXT,    \n' +\
                ' climate        TEXT,    \n' +\
                ' holdStatus     TEXT,    \n' +\
                ' holdUntil      TEXT     \n' +\
                ' )' 
            self.c[table].execute(create)
            tableX = table + 'X'
            createX = 'CREATE TABLE IF NOT EXISTS ' + tableX + ' ( \n' +\
                ' lastReading     TEXT, \n' +\
                ' runtimeDate     TEXT,     \n' +\
                ' runtimeInterval TEXT,     \n' +\
                ' dataTime        TEXT PRIMARY KEY,     \n' +\
                ' temperature     REAL,     \n' +\
                ' humidity        INTEGER,  \n' +\
                ' desiredHeat     REAL,     \n' +\
                ' desiredCool     REAL,     \n' +\
                ' hvacMode        TEXT,     \n' +\
                ' heatPump1       INTEGER,  \n' +\
                ' heatPump2       INTEGER,  \n' +\
                ' auxHeat1        INTEGER,  \n' +\
                ' auxHeat2        INTEGER,  \n' +\
                ' auxHeat3        INTEGER,  \n' +\
                ' cool1           INTEGER,  \n' +\
                ' cool2           INTEGER,  \n' +\
                ' fan             INTEGER   \n' +\
                ');'
            self.c[tableX] = self.DB.cursor()
            self.c[tableX].execute(createX)
            
        createW = 'CREATE TABLE IF NOT EXISTS Weather ( \n' +\
                ' id             INTEGER PRIMARY KEY, \n' +\
                ' timestamp      INTEGER DEFAULT CURRENT_TIMESTAMP, \n' +\
                ' station        TEXT,     \n' +\
                ' weatherSymbol  TEXT,     \n' +\
                ' dateTime       INTEGER,  \n' +\
                ' condition      INTEGER,  \n' +\
                ' temperature    REAL,     \n' +\
                ' pressure       INTEGER,  \n' +\
                ' humidity       INTEGER,  \n' +\
                ' dewpoint       REAL,     \n' +\
                ' visibility     REAL,     \n' +\
                ' windSpeed      INTEGER,  \n' +\
                ' windGust       INTEGER,  \n' +\
                ' windDirection  TEXT,     \n' +\
                ' windBearing    INTEGER,  \n' +\
                ' POP            INTEGER,  \n' +\
                ' tempHigh       REAL,     \n' +\
                ' tempLow        REAL,     \n' +\
                ' sky            TEXT      \n' +\
                ');'   
        self.c['Weather'] = self.DB.cursor()
        self.c['Weather'].execute(createW)
        # first entry is index '-2'
        self.weatherSymbol = ['no_symbol', 'n/a', 'sunny', 'few_clouds',
                              'partly_cloudy', 'mostly_cloudy', 'overcast',
                              'drizzle', 'rain', 'freezing_rain', 'showers',
                              'hail', 'snow', 'flurries', 'freezing_snow',
                              'blizzard', 'pellets', 'thunderstorm', 'windy',
                              'tornado', 'fog', 'haze', 'smoke', 'dust']
        self.sky = ['SUNNY', 'CLEAR', 'MOSTLY SUNNY', 'MOSTLY CLEAR',
                    'HAZY SUNSHINE', 'HAZE', 'PASSING CLOUDS',
                    'MORE SUN THAN CLOUDS', 'SCATTERED CLOUDS', 'PARTLY CLOUDY',
                    'A MIXTURE OF SUN AND CLOUDS', 'HIGH LEVEL CLOUDS',
                    'MORE CLOUDS THAN SUN', 'PARTLY SUNNY', 'BROKEN CLOUDS',
                    'MOSTLY CLOUDY', 'CLOUDY', 'OVERCAST', 'LOW CLOUDS',
                    'LIGHT FOG', 'FOG', 'DENSE FOG', 'ICE FOG', 'SANDSTORM',
                    'DUSTSTORM', 'INCREASING CLOUDINESS', 'DECREASING CLOUDINESS',
                    'CLEARING SKIES', 'BREAKS OF SUN LATE',
                    'EARLY FOG FOLLOWED BY SUNNY SKIES', 'AFTERNOON CLOUDS',
                    'MORNING CLOUDS', 'SMOKE', 'LOW LEVEL HAZE']
        
    def ExtRuntimeData(self, API):
        ERT = 'extendedRuntime'
        fiveMinutes = dt.timedelta(minutes = 5)
        for i in range(len(API.thermostatsExt)):
            table = API.thermostatsExt[i]['name'] + 'X'
            lastReading = dt.datetime.strptime(API.thermostatsExt[i][ERT]['lastReadingTimestamp'],
                                               '%Y-%m-%d %H:%M:%S')
            lastReading = lastReading.replace(tzinfo = tz.gettz('UTC'))
            lastReading = lastReading.astimezone(tz = tz.gettz('NewYork'))
            for intvl in range(-2, 1):
                j = int(intvl + 2)
                insert = 'INSERT OR REPLACE INTO ' + table + ' ( \n' \
                    'lastReading, runtimeDate, runtimeInterval, dataTime, temperature, \n' \
                    'humidity, desiredHeat, desiredCool, hvacMode, heatPump1, heatPump2, \n' \
                    'auxHeat1, auxHeat2, auxHeat3, cool1, cool2, fan ) \n' \
                    'Values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);'
                dataTime = lastReading + intvl * fiveMinutes
                #print(i, intvl, j, lastReading, dataTime)
                values = [lastReading,
                          API.thermostatsExt[i][ERT]['runtimeDate'],
                          API.thermostatsExt[i][ERT]['runtimeInterval'],
                          dataTime,
                          API.thermostatsExt[i][ERT]['actualTemperature'][j] / 10.0,
                          API.thermostatsExt[i][ERT]['actualHumidity'][j],
                          API.thermostatsExt[i][ERT]['desiredHeat'][j] / 10.0,
                          API.thermostatsExt[i][ERT]['desiredCool'][j] / 10.0,
                          API.thermostatsExt[i][ERT]['hvacMode'][j],
                          API.thermostatsExt[i][ERT]['heatPump1'][j],
                          API.thermostatsExt[i][ERT]['heatPump2'][j],
                          API.thermostatsExt[i][ERT]['auxHeat1'][j],
                          API.thermostatsExt[i][ERT]['auxHeat2'][j],
                          API.thermostatsExt[i][ERT]['auxHeat3'][j],
                          API.thermostatsExt[i][ERT]['cool1'][j],
                          API.thermostatsExt[i][ERT]['cool2'][j],
                          API.thermostatsExt[i][ERT]['fan'][j]
                          ]
                self.c[table].execute(insert, values)
                self.DB.commit()   

    def ThermostatData(self, API):
        for i in range(len(API.thermostats)):
            print(API.thermostats[i]['runtime']['actualTemperature'] / 10.0, \
                  API.thermostats[i]['runtime']['actualHumidity'], \
                  API.thermostats[i]['runtime']['lastStatusModified'], \
                  API.thermostats[i]['name'])
            table = API.thermostats[i]['name']
            insert = 'INSERT INTO ' + table + ' (\n' +\
                'statusTime, temp, humidity, coolSetPoint, heatSetPoint, \n' +\
                'coolStatus, heatStatus, fanStatus, fanOn, hvacMode, \n' +\
                'climate, holdStatus, holdUntil) \n' +\
                'VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'
            statusTime = dt.datetime.strptime(API.thermostats[i]['runtime']['lastStatusModified'],
                                              '%Y-%m-%d %H:%M:%S')
            statusTime = statusTime.replace(tzinfo = tz.gettz('UTC'))
            statusTime = statusTime.astimezone(tz = tz.gettz('NewYork'))
            if self.prevStatusTime[i] == statusTime:
                #print('Duplicate statusTime:', statusTime, ' - skipping', i)
                continue
            else:
                self.prevStatusTime[i] = statusTime
            coolStatus = findSubstr(API.thermostats[i]['equipmentStatus'], 'cool')
            heatStatus = findSubstr(API.thermostats[i]['equipmentStatus'], 'heat')
            if findSubstr(API.thermostats[i]['equipmentStatus'], 'fan') == 'fan':
                fanOn      = 'on' 
            else:
                fanOn      = 'off'
            holdUntil = API.thermostats[i]['events'][0]['endDate'] + ' ' + \
                API.thermostats[i]['events'][0]['endTime']       
            if API.thermostats[i]['events'][0]['type'] == 'hold':
                holdStatus = 'hold'
            elif API.thermostats[i]['events'][0]['type'] == 'vacation':
                holdStatus = 'vacation'
            else:
                holdStatus = holdUntil = None
            values = [statusTime,
                      API.thermostats[i]['runtime']['actualTemperature'] / 10.0,
                      API.thermostats[i]['runtime']['actualHumidity'],
                      API.thermostats[i]['runtime']['desiredCool'] /10.0,
                      API.thermostats[i]['runtime']['desiredHeat'] /10.0,
                      coolStatus,
                      heatStatus,
                      API.thermostats[i]['runtime']['desiredFanMode'],
                      fanOn,
                      API.thermostats[i]['settings']['hvacMode'],
                      API.thermostats[i]['program']['currentClimateRef'],
                      holdStatus,
                      holdUntil]
            self.c[table].execute(insert, values)
            self.DB.commit()

    def WeatherData(self, API):
        insert = 'INSERT INTO Weather ( \n' +\
            'station, weatherSymbol, dateTime, condition, temperature, pressure, \n' +\
            'humidity, dewpoint, visibility, windSpeed, windGust, windDirection,   \n' +\
            'windBearing, POP, tempHigh, tempLow, sky) \n' +\
            'VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);'
        dateTime = dt.datetime.strptime(API.thermostats[0]['weather']['forecasts'][0]['dateTime'],
                                         '%Y-%m-%d %H:%M:%S')
        if self.prevWeather == dateTime:
            #print('Skip duplicate weather')
            return
        else:
            self.prevWeather = dateTime
        symbol = API.thermostats[0]['weather']['forecasts'][0]['weatherSymbol']
        symbol = self.weatherSymbol[symbol].title()
        gust = API.thermostats[0]['weather']['forecasts'][0]['windGust']
        if gust == -5002:
            gust = None
        sky = API.thermostats[0]['weather']['forecasts'][0]['sky']
        sky = self.sky[2 + sky].title()    #first entry is -2
        values = [API.thermostats[0]['weather']['weatherStation'],
                  symbol,
                  dateTime,
                  API.thermostats[0]['weather']['forecasts'][0]['condition'],
                  API.thermostats[0]['weather']['forecasts'][0]['temperature'] / 10.0,
                  API.thermostats[0]['weather']['forecasts'][0]['pressure'],
                  API.thermostats[0]['weather']['forecasts'][0]['relativeHumidity'],
                  API.thermostats[0]['weather']['forecasts'][0]['dewpoint'] / 10.0,
                  API.thermostats[0]['weather']['forecasts'][0]['visibility'] * 0.000621371,
                  API.thermostats[0]['weather']['forecasts'][0]['windSpeed'],
                  gust,
                  API.thermostats[0]['weather']['forecasts'][0]['windDirection'],
                  API.thermostats[0]['weather']['forecasts'][0]['windBearing'],
                  API.thermostats[0]['weather']['forecasts'][0]['pop'],
                  API.thermostats[0]['weather']['forecasts'][0]['tempHigh'] / 10.0,
                  API.thermostats[0]['weather']['forecasts'][0]['tempLow'] / 10.0,
                  sky]
        self.c['Weather'].execute(insert, values)
        self.DB.commit()
    
            
class ecobee(pyecobee.Ecobee):
    def __init__(self,  config_filename: str = None, config: dict = None):
        pyecobee.Ecobee.__init__(self, config_filename = config_filename, config = config)
        self.pp = pprint.PrettyPrinter(indent=4, sort_dicts=False)
        
    def getTokens(self):
        attempts = 32
        delay = 30
        for attempt in range(attempts):
            rc = self.request_tokens()
            if rc:
                print('attempt:', attempt, 'Got tokens')
                return True
            else:
                print('attempt:', attempt, 'Failed to get tokens')
                time.sleep(delay)
        return False

    def getThermostatData(self):
        if self.access_token is None:
            rc = self.request_pin()
            print('request pin:', rc, ' PIN:', self.pin)
            rc = self.getTokens()
            print('get tokens:', rc)
            self.dumpEcobee()
            self._write_config()
        
        try:
            rc = self.get_thermostats()
        
        except pyecobee.errors.ExpiredTokenError as e:
            #print('type is:', e.__class__.__name__)
            #print_exc()
            #print('YYYY')
            rc = self.refresh_tokens()
            if rc:
                self._write_config()
                rc = self.get_thermostats()
                if not rc:
                    print('get_thermostats() failed again')
        #print('thermostats:')
        #pp.pprint(API.thermostats)

    def getExtThermostats(self) -> bool:
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
            #print('thermostatsExt:0')
            self.thermostatsExt = response["thermostatList"]
            #print('thermostatsExt:1')
            #self.pp.pprint(self.thermostatsExt)
            return True
        except (KeyError, TypeError):
            print('type is:', e.__class__.__name__)
            print_exc()
            return False
        except pyecobee.errors.ExpiredTokenError as e:
            #print('type is:', e.__class__.__name__)
            #print_exc()
            print('YYYY')
            rc = self.refresh_tokens()
            if rc:
                self._write_config()
                rc = self.getExtTthermostats()
                if not rc:
                    print('get_thermostats() failed again')

        
    def dumpEcobee(self):
        print('thermostats:', self.thermostats)
        print('config_file:', self.config_filename)
        print('config:', self.config)
        print('api_key:', self.api_key)
        print('pin:', self.pin)
        print('.authorization_code:', self.authorization_code)
        print('access_token:', self.access_token)
        print('refresh_token:', self.refresh_token)

def main():
    # want unbuffered stdout for use with "tee"
    buffered = os.getenv('PYTHONUNBUFFERED')
    if buffered is None:
        myenv = os.environ.copy()
        myenv['PYTHONUNBUFFERED'] = 'Please'
        os.execve(sys.argv[0], sys.argv, myenv)
    pp = pprint.PrettyPrinter(indent=4, sort_dicts=False)
    #config = {'API_KEY' : 'ObsoleteAPIkey', 'INCLUDE_NOTIFICATIONS' : 'True'}
    #API = pyecobee.Ecobee(config = config)
    API = ecobee(config_filename = 'ecobee.conf')
    setLogging(pyecobee._LOGGER)
    API.read_config_from_file()
    save = saveEcobeeData()
    #umpEcobee(API)

    while True:
        API.getThermostatData()
        save.ThermostatData(API)
        save.WeatherData(API)
        API.getExtThermostats()
        save.ExtRuntimeData(API)
        time.sleep(179)





if __name__ == '__main__':
  main()
