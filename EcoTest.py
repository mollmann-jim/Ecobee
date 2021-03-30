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
import sched
from traceback import print_exc

def setLogging(logger):
    global LOGFILE
    logger.setLevel(logging.DEBUG)
    # create file handler which logs even debug messages
    #fh = logging.FileHandler('ecobee.log')
    fh = logging.FileHandler(LOGFILE)
    fh.setLevel(logging.ERROR)
    fh.setLevel(logging.WARNING)
    #fh.setLevel(logging.DEBUG)
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
        global DBname
        self.prevStatusTime = [0, 0]
        #DBname = '/home/jim/tools/Ecobee/MBthermostat.sched.sql'
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
        #print(dt.datetime.now(), 'save.ExtRuntimeData')
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
        #print(dt.datetime.now(), 'save.ThermostatData')
        if API.thermostats is None:
            # wait for initialization
            return
        for i in range(len(API.thermostats)):
            '''
            print(API.thermostats[i]['runtime']['actualTemperature'] / 10.0, \
                  API.thermostats[i]['runtime']['actualHumidity'], \
                  API.thermostats[i]['runtime']['lastStatusModified'], \
                  API.thermostats[i]['name'])
            '''
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
            events = [API.getCurrentMode(i, 0), API.getCurrentMode(i, 1)]
            holdStatus = holdUntil = None
            for j in range(2):
                if events[j][:1] == '*':
                    holdUntil = API.thermostats[i]['events'][j]['endDate'] + ' ' + \
                        API.thermostats[i]['events'][j]['endTime']
                    holdStatus = events[j][1:]
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
        #print(dt.datetime.now(), 'save.WeatherData')
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
        #print(dt.datetime.now(), 'getThermostatData')
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
        #self.pp.pprint(self.thermostats)
        
    def getWeather(self):
        # rely on the data returned by getThermostatData()
        #print(dt.datetime.now(), 'getWeather')
        pass

        
    def dumpEcobee(self):
        print('thermostats:', self.thermostats)
        print('config_file:', self.config_filename)
        print('config:', self.config)
        print('api_key:', self.api_key)
        print('pin:', self.pin)
        print('.authorization_code:', self.authorization_code)
        print('access_token:', self.access_token)
        print('refresh_token:', self.refresh_token)
        
    def getCurrentMode(self, index, event):
        name = '  '
        if index >= len(self.thermostats) or event >= len(self.thermostats[index]['events']):
            return name
        if self.thermostats[index]['events'][event]['type'] == 'vacation':
            name = 'vacation'
        elif self.thermostats[index]['events'][event]['type'] == 'hold':
            name = self.thermostats[index]['events'][event]['holdClimateRef']
        elif self.thermostats[index]['events'][event]['type'] == 'template':
            name = '  '
        else:
            name = 'unknown'
        if self.thermostats[index]['events'][event]['running']:
            name = '*' + name
        return name

class Status():
    def __init__(self, scheduler):
        self.scheduler = scheduler
        self.starttime = 0
        
    def Schedule(self, API, Printer, hours = 0, minutes = 0, seconds = 0):
        self.frequency = dt.timedelta(hours = hours, minutes = minutes, seconds = seconds)
        self.Printer   = Printer
        self.API       = API
        now = dt.datetime.now()
        firstTime = now.replace(hour = 0, minute = 0, second = 0, microsecond = 0) -\
                    dt.timedelta(weeks = 1)
        while firstTime < now:
            firstTime += self.frequency
        self.starttime = firstTime
        #print('Schedule Start time:', self.starttime)
        self.scheduler.enterabs(time.mktime(self.starttime.timetuple()), 1, self.Printer, ())

    def printHeaderLine(self, reschedule = True):
        self.starttime = self.starttime + self.frequency
        if reschedule:
            self.scheduler.enterabs(time.mktime(self.starttime.timetuple()), 1, self.Printer, ())
        hdr = '{:^10s} {:^8s} {:6s} {:4s} {:4s} {:4s} {:4s} {:9s} {:9s}  {:6s} {:4s} {:4s} {:4s} {:4s} {:9s} {:9s}'
        print(hdr.format('Date', 'Time',
                         'Thermo', 'Temp', 'Hum.', 'Heat', 'Cool', 'Event0', 'Event1',
                         'Thermo', 'Temp', 'Hum.' , 'Heat', 'Cool', 'Event0', 'Event1'))

    def addLine(self, note):
        self.printStatusLine(note = note, reschedule = False)
        
    def printStatusLine(self, note = '', reschedule = True):
        #self.dump()
        self.starttime = self.starttime + self.frequency
        if reschedule:
            self.scheduler.enterabs(time.mktime(self.starttime.timetuple()), 1, self.Printer, ())
        if self.API.thermostats is None:
            # wait for initialization
            return
        fmt = '{:^6s} {:4.1f} {:^4d} {:4.1f} {:4.1f} {:^9s} {:^9s}  '
        fmt = '{:17s} ' + fmt + fmt + ' {:s}'
        now = dt.datetime.now().replace(microsecond = 0)
        Name = [[]]
        # fill the array in case there is only the "template" event
        for i in range(2):
            Name.append([])
            for j in range(2):
                Name[i].append('   ')
        # There may be 3 or more events. E.g. vacation, climate hold, template
        for i in range(len(self.API.thermostats)):
            if i > 1:
                Name.append([])
            for j in range(len(self.API.thermostats[i]['events'])):
                try:
                    if j > 1:
                        Name[i].append(self.API.getCurrentMode(i, j))
                    else:
                        Name[i][j] = (self.API.getCurrentMode(i, j))
                except:
                    print(i, j, Name)
                    pp = pprint.PrettyPrinter(indent=4, sort_dicts=False)
                    pp.pprint(self.API.thermostats)
        print(fmt.format(str(now),
                         self.API.thermostats[0]['name'].replace('stairs', ''),
                         self.API.thermostats[0]['runtime']['actualTemperature'] / 10.0,
                         self.API.thermostats[0]['runtime']['actualHumidity'],
                         self.API.thermostats[0]['runtime']['desiredHeat'] / 10.0,
                         self.API.thermostats[0]['runtime']['desiredCool'] / 10.0,
                         Name[0][0],
                         Name[0][1],
                         self.API.thermostats[1]['name'].replace('stairs', ''),
                         self.API.thermostats[1]['runtime']['actualTemperature'] / 10.0,
                         self.API.thermostats[0]['runtime']['actualHumidity'],
                         self.API.thermostats[1]['runtime']['desiredHeat'] / 10.0,
                         self.API.thermostats[1]['runtime']['desiredCool'] / 10.0,
                         Name[1][0],
                         Name[1][1],
                         note
                         ))
    def dump(self):
        print(self)
        print(self.scheduler)
        print(self.API)
        print(self.starttime)
        print(self.frequency)

class collectThermostatData:
    def __init__(self, scheduler):
        self.scheduler = scheduler
        self.starttime = 0

    def Schedule(self, Getter, Saver, API, hours = 0, minutes = 0, seconds = 0):
        self.frequency = dt.timedelta(hours = hours, minutes = minutes, seconds = seconds)
        self.Getter    = Getter
        self.Saver     = Saver
        self.API       = API
        now = dt.datetime.now()
        firstTime = now.replace(hour = 0, minute = 0, second = 0, microsecond = 0) -\
                    dt.timedelta(weeks = 1)
        while firstTime < now:
            firstTime += self.frequency
        self.starttime = firstTime
        #print('Schedule Start time:', self.starttime)
        self.scheduler.enterabs(time.mktime(self.starttime.timetuple()), 1, self.Collector, ())

    def Collector(self):
        # reschedule
        self.starttime = self.starttime + self.frequency
        self.scheduler.enterabs(time.mktime(self.starttime.timetuple()), 1, self.Collector, ())
        self.Getter()
        self.Saver(self.API)

class deHumidify:
    def __init__(self, scheduler):
        self.scheduler = scheduler
        self.starttime = 0
        self.pp = pprint.PrettyPrinter(indent=4, sort_dicts=False)
        
    def Schedule(self, API, Status, startHour = 6, startMinute = 30, duration = 30):
        self.API = API
        self.Status = Status
        self.duration = duration
        #print(dt.datetime.now(), 'deHumidify.Schedule')
        now = dt.datetime.now()
        firstTime = now.replace(hour = startHour, minute = startMinute,
                                second = 0, microsecond = 0) - dt.timedelta(days = 1)
        while firstTime < now:
            firstTime += dt.timedelta(days = 1)
        self.starttime = firstTime
        #print('deHumidify.Schedule Start time:', self.starttime)
        ##### testing
        #firstTime = now + dt.timedelta(seconds = 11)
        #self.starttime = firstTime
        #print('deHumidify.Schedule Start time:', self.starttime)
        #####
        self.scheduler.enterabs(time.mktime(self.starttime.timetuple()), 1, self.forceRun, ())

    def forceRun(self):
        #print(dt.datetime.now(), 'deHumidify.forceRun')
        # allow getThermostatData to run first
        if self.API.thermostats is  None:
            retry = dt.datetime.now() + dt.timedelta(minutes = 1)
            #print('deHumidify.forceRun try again at ', retry)
            self.scheduler.enterabs(time.mktime(retry.timetuple()), 1, self.forceRun, ())
            return
        #print('deHumidify.forceRun has data')
        self.starttime += dt.timedelta(days = 1)
        self.scheduler.enterabs(time.mktime(self.starttime.timetuple()), 1, self.forceRun, ())
        #print('deHumidify.forceRun next:', self.starttime)

        for i in range(len(self.API.thermostats)):
            events = [self.API.getCurrentMode(i, 0), self.API.getCurrentMode(i, 1)]
            if 'vacation' not in events[0] and 'vacation' not in events[1]:
                print('thermostat', i, 'not running in vacation mode')
                print(events)
                return

        icebox = 'smart1'
        oven   = 'smart2'
        indoorTemp  = 0.0
        outdoorHigh = 0.0
        for i in range(len(self.API.thermostats)):
            indoorTemp  += self.API.thermostats[i]['runtime']['actualTemperature']
            outdoorHigh += self.API.thermostats[i]['weather']['forecasts'][0]['tempHigh']
        indoorTemp  = indoorTemp  / 10.0 / len(self.API.thermostats)
        outdoorHigh = outdoorHigh / 10.0 / len(self.API.thermostats)
        if indoorTemp >= 65 and outdoorHigh > 70.0:
            climate = icebox
        else:
            climate = oven
        note = 'inTemp: {:4.1f} outHigh: {:4.1f} climate: {:s}'.format(indoorTemp,
                                                                       outdoorHigh,
                                                                       climate)
        self.Status(note)

        vacation = self.API.thermostats[0]['events'][0]
        
        self.API.Delete_vacation(index = 0, vacation = vacation['name'])
        time.sleep(10)
        self.API.getThermostatData()
        self.Status('deHumidify: vacation deleted')

        finish = dt.datetime.now() + dt.timedelta(minutes = self.duration)
        # add new vacation to start after hold
        self.API.Create_vacation(index = 0,
                                 vacation_name = 'notAround',
                                 cool_temp     = int(vacation['coolHoldTemp']) / 10,
                                 heat_temp     = int(vacation['heatHoldTemp']) / 10,
                                 start_date    = str(finish.date()),
                                 start_time    = str(finish.time())[0:8],
                                 end_date      = vacation['endDate'],
                                 end_time      = vacation['endTime']
                                 )
        time.sleep(10)
        self.API.getThermostatData()
        self.Status('deHumidify: vacation created')
        #self.pp.pprint(self.API.thermostats)

        for i in range(len(self.API.thermostats)):
            self.API.Set_Climate_hold(index = i,
                                      climate   = climate,
                                      hold_type = 'dateTime',
                                      end_date  = str(finish.date()),
                                      end_time  = str(finish.time())[0:8]
                                      )
            time.sleep(10)
        time.sleep(10)
        self.API.getThermostatData()
        self.Status('deHumidify: climate hold added\n\n')
        self.pp.pprint(self.API.thermostats)
        
        
def main():
    pp = pprint.PrettyPrinter(indent=4, sort_dicts=False)
    #config = {'API_KEY' : 'ObsoleteAPIkey', 'INCLUDE_NOTIFICATIONS' : 'True'}
    #API = pyecobee.Ecobee(config = config)
    API = ecobee(config_filename = 'ecobee.conf')
    setLogging(pyecobee._LOGGER)
    API.read_config_from_file()
    # intialize API.thermostats
    API.getThermostatData()
    save = saveEcobeeData()
 
    # Build a scheduler object that will look at absolute times
    scheduler = sched.scheduler(time.time, time.sleep)

    runtime = collectThermostatData(scheduler)
    runtime.Schedule(API.getThermostatData, save.ThermostatData, API, minutes = 2, seconds = 45)
    extRuntime = collectThermostatData(scheduler)
    extRuntime.Schedule(API.getExtThermostats, save.ExtRuntimeData, API, minutes = 12)
    
    weather = collectThermostatData(scheduler)
    weather.Schedule(API.getWeather, save.WeatherData, API, minutes = 25)

    header = Status(scheduler)
    header.Schedule(API, header.printHeaderLine, minutes = 40)
    status = Status(scheduler)
    status.Schedule(API, status.printStatusLine, minutes = 3)

    dehumidify = deHumidify(scheduler)
    dehumidify.Schedule(API, status.addLine, startHour = 6, startMinute = 30, duration = 30)

    ###############3 debug
    '''
    DH = dt.datetime.now().replace(microsecond = 0) + dt.timedelta(minutes = 10)
    dehumidify.Schedule(API, status.addLine, startHour = DH.hour,
                        startMinute = DH.minute, duration = 30)
    '''
    ###############
    
    print(len(scheduler.queue))
    #print(scheduler.queue)
    for event in scheduler.queue:
        print(dt.datetime.fromtimestamp(event.time), str(event.action).split(' ')[2])

    print('\n\n')
    header.printHeaderLine(reschedule = False)

    scheduler.run()

if 'sched' in sys.argv[0]:
    DBname  = '/home/jim/tools/Ecobee/MBthermostat.sched.sql'
    LOGFILE = '/home/jim/tools/Ecobee/ecobee.sched.log'
else:
    DBname  = '/home/jim/tools/Ecobee/MBthermostat.sql'
    LOGFILE = '/home/jim/tools/Ecobee/ecobee.log'

if __name__ == '__main__':
    # want unbuffered stdout for use with "tee"
    buffered = os.getenv('PYTHONUNBUFFERED')
    if buffered is None:
        myenv = os.environ.copy()
        myenv['PYTHONUNBUFFERED'] = 'Please'
        os.execve(sys.argv[0], sys.argv, myenv)
    main()
