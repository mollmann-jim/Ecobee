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
import subprocess
from traceback import print_exc, print_stack
from dateutil.relativedelta import relativedelta
from zoneinfo import ZoneInfo

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

def doCmd(command, printFailure = True, debug = False):
    if debug: print('doCmd:command:', command)
    result = subprocess.run(command, shell = True, stdout = subprocess.PIPE, \
                            stderr=subprocess.STDOUT)
    if result.returncode != 0 & printFailure:
        #print(result.stdout)
        print('Failed: RC:', result.returncode, command)
        print(result.stderr)
    if debug: print('doCmd:result:', result)
    return result

backupModelastCheck = None
backupModeActive    = False
class backupMode:
    def __init__(self, frequency = 900):
        self.frequency = frequency
        global backupModelastCheck, backupModeActive
        backupModelastCheck = dt.datetime.now() - \
            dt.timedelta(seconds = 1 + self.frequency)
        backupModeActive = False

    def active(self):
        global backupModelastCheck, backupModeActive
        host = doCmd('/usr/bin/hostname').stdout.decode('utf-8').rstrip('\n')
        if host == 'jim4':
            backupModeActive = False
        else:   
            if dt.datetime.now() - backupModelastCheck > dt.timedelta(seconds = self.frequency):
                backupModelastCheck = dt.datetime.now()
                cmd = '/usr/bin/ssh jim ps -efw | grep EcoBee.py'
                result = doCmd(cmd)
                #print(result.returncode)
                if result.returncode == 0:
                    backupModeActive = True
                else:
                    backupModeActive = False
        #print('backupMode.active:', backupModeActive)
        return backupModeActive
    
class fdPrint:
    def __init__(self, fd):
        self.fd = fd
        self.file = os.fdopen(self.fd, 'w', 1)

    def Print(self, line):
        myLine = str.encode(line)
        os.write(self.fd, myLine)
        if not os.isatty(self.fd):
            os.fsync(self.fd)

class normalTermostatModes:
    def  __init__(self):
        self.savedHVACmodes = {}
        self.currentHVACmodes = {}
        
    def current(self, thermostat, mode):
        #print('normalTermostatModes:current', thermostat, mode)
        self.currentHVACmodes[thermostat] = mode

    def update(self, Saver):
        for thermostat in self.currentHVACmodes:
            curMode = self.currentHVACmodes[thermostat]
            savMode = self.savedHVACmodes.get(thermostat, None)
            if curMode == 'off' or curMode == None or curMode == savMode:
                pass
            else:
                Saver(thermostat, curMode)
                print('normalTermostatModes:update', thermostat, savMode, '->', curMode)
                self.savedHVACmodes[thermostat] = curMode

    def get(self):
        return self.savedHVACmodes

    def getSaved(self, DBgetSaved):
        self.savedHVACmodes = DBgetSaved()
        print('normalTermostatModes:getSaved', self.savedHVACmodes)
        
class saveEcobeeData():
    def __init__(self, HVACmode, thermostats = [], where = 'noWhere'):
        global DBname
        self.prevStatusTime = [0, 0, 0, 0]
        self.thermostats = thermostats
        self.where = where
        self.DB = sqlite3.connect(DBname)
        self.DB.row_factory = sqlite3.Row
        self.c = {}
        self.initDB()
        self.prevWeather = 0
        self.normalModes = HVACmode
        self.pp = pprint.PrettyPrinter(indent=4, sort_dicts=False)
        self.tz = self.TZ()
        
    def initDB(self):
        for table in self.thermostats:
            self.c[table] = self.DB.cursor()
            #drop = 'DROP TABLE IF EXISTS ' + table + ';'
            #c[table].execute(drop)
            create = 'CREATE TABLE IF NOT EXISTS ' + table + '( \n' +\
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
            index  = 'CREATE INDEX IF NOT EXISTS ' + table + 'index ON ' +\
                table + ' (statusTime);'
            self.c[table].execute(index)

            tableX = table + 'X'
            self.c[tableX] = self.DB.cursor()
            createX = 'CREATE TABLE IF NOT EXISTS ' + tableX + ' ( \n' +\
                ' lastReading     TEXT,             \n' +\
                ' runtimeDate     TEXT,             \n' +\
                ' runtimeInterval TEXT,             \n' +\
                ' dataTime        TEXT PRIMARY KEY, \n' +\
                ' temperature     REAL,             \n' +\
                ' humidity        INTEGER,          \n' +\
                ' desiredHeat     REAL,             \n' +\
                ' desiredCool     REAL,             \n' +\
                ' hvacMode        TEXT,             \n' +\
                ' heatPump1       INTEGER,          \n' +\
                ' heatPump2       INTEGER,          \n' +\
                ' auxHeat1        INTEGER,          \n' +\
                ' auxHeat2        INTEGER,          \n' +\
                ' auxHeat3        INTEGER,          \n' +\
                ' cool1           INTEGER,          \n' +\
                ' cool2           INTEGER,          \n' +\
                ' fan             INTEGER           \n' +\
                ');'
            self.c[tableX].execute(createX)
            index  = 'CREATE INDEX IF NOT EXISTS ' + table + 'index ON ' +\
                table + ' (dataTime);'
            self.c[tableX].execute(index)

            tableR = table + 'R'
            self.c[tableR] = self.DB.cursor()            
            drop = 'DROP TABLE IF EXISTS ' + tableR + ';'
            self.c[tableR].execute(drop)
            '''
            database          runtimeReport column
            ----------------  ---------------------
            dataTime          
            temperature       zoneAveTemp 
            humidity          zoneHumidity
            desiredHeat       zoneHeatTemp
            desiredCool       zoneCoolTemp
            hvacMode          hvacMode
            heatPump1         compHeat1
            heatPump2         compHeat2
            auxHeat1          auxHeat1
            auxHeat2          auxHeat2
            auxHeat3          auxHeat3
            cool1             compCool1
            cool2             compCool2
            fan               fan
            outdoorHumidity   outdoorHumidity
            outdoorTemp,      outdoorTemp
            sky               sky
            wind              wind
            zoneCalendarEvent zoneCalendarEvent
            zoneClimate       zoneClimate
            zoneHvacMode      zoneHvacMode
            zoneOccupancy     zoneOccupancy
            dmOffset          dmOffset
            economizer        economizer
            '''
            createR = 'CREATE TABLE IF NOT EXISTS ' + tableR + ' ( \n' +\
                ' dataTimeTZ        TEXT PRIMARY KEY, \n' +\
                ' dataTime          TEXT,             \n' +\
                ' temperature       REAL,             \n' +\
                ' humidity          INTEGER,          \n' +\
                ' desiredHeat       INTEGER,          \n' +\
                ' desiredCool       INTEGER,          \n' +\
                ' hvacMode          TEXT,             \n' +\
                ' heatPump1         INTEGER,          \n' +\
                ' heatPump2         INTEGER,          \n' +\
                ' auxHeat1          INTEGER,          \n' +\
                ' auxHeat2          INTEGER,          \n' +\
                ' auxHeat3          INTEGER,          \n' +\
                ' cool1             INTEGER,          \n' +\
                ' cool2             INTEGER,          \n' +\
                ' fan               INTEGER,          \n' +\
                ' outdoorHumidity   INTEGER,          \n' +\
                ' outdoorTemp,      INTEGER,          \n' +\
                ' sky               INTEGER,          \n' +\
                ' wind              INTEGER,          \n' +\
                ' zoneCalendarEvent TEXT,             \n' +\
                ' zoneClimate       TEXT,             \n' +\
                ' zoneHvacMode      TEXT,             \n' +\
                ' zoneOccupancy     INTEGER,          \n' +\
                ' dmOffset          REAL,             \n' +\
                ' economizer        INTEGER           \n' +\
                ');'
            self.c[tableR] = self.DB.cursor()
            self.c[tableR].execute(createR)
            index  = 'CREATE INDEX IF NOT EXISTS ' + table + 'index ON ' +\
                table + ' (dataTimeTZ);'
            self.c[tableR].execute(index)
            
        createW = 'CREATE TABLE IF NOT EXISTS Weather' + self.where + ' ( \n' +\
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
        
        self.weatherSymbol = ['no symbol', 'n/a', 'sunny', 'few clouds',
                              'partly cloudy', 'mostly cloudy', 'overcast',
                              'drizzle', 'rain', 'freezing rain', 'showers',
                              'hail', 'snow', 'flurries', 'freezing snow',
                              'blizzard', 'pellets', 'thunderstorm', 'windy',
                              'tornado', 'fog', 'haze', 'smoke', 'dust']
        self.sky = ['N/A', 'SUNNY', 'CLEAR', 'MOSTLY SUNNY', 'MOSTLY CLEAR',
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

        self.c['HVACmode'] = self.DB.cursor()
        #drop = 'DROP TABLE IF EXISTS HVACmode;'
        #self.c['HVACmode'].execute(drop)
        create = 'CREATE TABLE IF NOT EXISTS HVACmode ( \n' +\
            ' thermostat TEXT PRIMARY KEY, \n' +\
            ' HVACmode   TEXT,    \n' +\
            ' timestamp  INTEGER \n' +\
            ' );'
        self.c['HVACmode'].execute(create)
        
    def ExtRuntimeData(self, API):
        #print(dt.datetime.now(), 'save.ExtRuntimeData')
        ERT = 'extendedRuntime'
        fiveMinutes = dt.timedelta(minutes = 5)
        for i in range(len(API.thermostatsExt)):
            #print('XXX name:',  API.thermostatsExt[i]['name'], i)
            if API.thermostatsExt[i]['name'] not in self.thermostats:
                #print('XXX skipping')
                continue
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
            #print('ZZZ name:',  API.thermostats[i]['name'], i)
            self.normalModes.current(API.thermostats[i]['name'],
                                     API.thermostats[i]['settings']['hvacMode'])
            if API.thermostats[i]['name'] not in self.thermostats:
                #print('ZZZ skipping')
                continue
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
        self.normalModes.update(self.saveHVACmode)

    def saveHVACmode(self, thermostat, mode):
        now = dt.datetime.now()
        insert = 'INSERT OR REPLACE INTO HVACmode' +\
            ' (thermostat, HVACmode, timestamp)' +\
            ' VALUES( ?, ?, ? );'
        values = (thermostat, mode, now)
        self.c['HVACmode'].execute(insert, values)
        print('saveHVACmode update:', thermostat, mode, now)
        self.DB.commit()

    def getSavedHVACmodes(self):
        modes = {}
        select = 'SELECT thermostat, HVACmode, timestamp FROM HVACmode;'
        self.c['HVACmode'].execute(select)
        result = self.c['HVACmode'].fetchall()
        for rec in result:
            print(rec['thermostat'], rec['HVACmode'], rec['timestamp'])
            modes[rec['thermostat']] = rec['HVACmode']
        print('getSavedHVACmodes', modes)
        return modes

    def WeatherData(self, API):
        #print(dt.datetime.now(), 'save.WeatherData')
        insert = 'INSERT INTO Weather' + self.where + ' ( \n' +\
            'station, weatherSymbol, dateTime, condition, temperature, pressure, \n' +\
            'humidity, dewpoint, visibility, windSpeed, windGust, windDirection,   \n' +\
            'windBearing, POP, tempHigh, tempLow, sky) \n' +\
            'VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);'
        W = None
        #print('WeatherData:', self.where)
        for i in range(len(API.thermostats)):
            if API.thermostats[i]['name'] in self.thermostats:
                W = i
        if W is None:
            print('WeatherData: did not find matching thermostat', self.where, self.thermostats)
            return
        dateTime = dt.datetime.strptime(API.thermostats[W]['weather']['forecasts'][0]['dateTime'],
                                         '%Y-%m-%d %H:%M:%S')
        if self.prevWeather == dateTime:
            #print('Skip duplicate weather')
            return
        else:
            self.prevWeather = dateTime
        symbol = API.thermostats[W]['weather']['forecasts'][0]['weatherSymbol']
        symbol += 2    # first entry is -2, offset for []
        if symbol < 0 or symbol >= len(self.weatherSymbol):
            symbol = None
        else:
            symbol = self.weatherSymbol[symbol].title()
        gust = API.thermostats[W]['weather']['forecasts'][0]['windGust']
        if gust == -5002:
            gust = None
        sky = API.thermostats[W]['weather']['forecasts'][0]['sky']
        if sky < 0 or sky >= len(self.sky):
            sky = None
        else:
            sky = self.sky[sky].title() 
        values = [API.thermostats[W]['weather']['weatherStation'],
                  symbol,
                  dateTime,
                  API.thermostats[W]['weather']['forecasts'][0]['condition'],
                  API.thermostats[W]['weather']['forecasts'][0]['temperature'] / 10.0,
                  API.thermostats[W]['weather']['forecasts'][0]['pressure'],
                  API.thermostats[W]['weather']['forecasts'][0]['relativeHumidity'],
                  API.thermostats[W]['weather']['forecasts'][0]['dewpoint'] / 10.0,
                  API.thermostats[W]['weather']['forecasts'][0]['visibility'] * 0.000621371,
                  API.thermostats[W]['weather']['forecasts'][0]['windSpeed'],
                  gust,
                  API.thermostats[W]['weather']['forecasts'][0]['windDirection'],
                  API.thermostats[W]['weather']['forecasts'][0]['windBearing'],
                  API.thermostats[W]['weather']['forecasts'][0]['pop'],
                  API.thermostats[W]['weather']['forecasts'][0]['tempHigh'] / 10.0,
                  API.thermostats[W]['weather']['forecasts'][0]['tempLow'] / 10.0,
                  sky]
        self.c['Weather'].execute(insert, values)
        self.DB.commit()

    def RuntimeReportData(self, API, startDate, endDate):
        longAgo  = dt.timedelta(days = 365)
        nowDelta = dt.timedelta(days = 0)
        now      = dt.datetime.now()
        columnNames = 'dataTimeTZ, dataTime, temperature, humidity, desiredHeat, '   \
            'desiredCool, hvacMode, heatPump1, heatPump2, auxHeat1, auxHeat2, '      \
            'auxHeat3, cool1, cool2, fan, outdoorHumidity, outdoorTemp, sky, '       \
            'wind, zoneCalendarEvent, zoneClimate, zoneHvacMode, zoneOccupancy, '    \
            'dmOffset, economizer'
        rows0 =  API.runtimeReportData[0]['rowCount']
        print('saveEcobeeData.RuntimeReportData:', startDate, endDate, 'rows:', rows0, '\n')
        for i in range(len(API.runtimeReportData)):
            found = False
            myID = API.runtimeReportData[i]['thermostatIdentifier']
            for j in range(len(API.thermostats)):
                if API.thermostats[j]['identifier'] == myID:
                    thermoName = API.thermostats[j]['name']
                    table = thermoName + 'R'
                    found = True
                    break
            if not found:
                print('unable to find thermostat ',
                      API.runtimeReportData[i]['thermostatIdentifier'])
            myRunt = API.runtimeReportData[i]['rowList']
            for row in myRunt:
                myday, mytime, temperature, humidity, desiredHeat, desiredCool, \
                hvacMode, heatPump1, heatPump2, auxHeat1, auxHeat2, auxHeat3,   \
                cool1, cool2, fan, outdoorHumidity, outdoorTemp, sky, wind,     \
                zoneCalendarEvent, zoneClimate, zoneHvacMode, zoneOccupancy,    \
                dmOffset, economizer = row.split(",")
                date_str = str(myday) + " " + str(mytime)
                myDataTime = dt.datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
                dataTime = myDataTime.isoformat(sep = ' ')
                dataTimeTZ = self.tz.addTZ(myDataTime)
                dataTimetz = dataTimeTZ.isoformat(sep = ' ')
                nRow = [dataTimetz, dataTime, temperature, humidity,                   \
                        desiredHeat, desiredCool, hvacMode, heatPump1, heatPump2,      \
                        auxHeat1, auxHeat2, auxHeat3, cool1, cool2, fan,               \
                        outdoorHumidity, outdoorTemp, sky, wind, zoneCalendarEvent,    \
                        zoneClimate, zoneHvacMode, zoneOccupancy, dmOffset, economizer]

                select = 'SELECT ' + columnNames + ' FROM ' + table + \
                    ' WHERE dataTimetz IS ? ;'
                OldRow = {}
                self.c[table].execute(select, (dataTimetz,))
                oldRow = self.c[table].fetchone()
                update = True
                if oldRow is None:
                    #print('oldRow is None')
                    pass
                else:
                    OLDRow = dict(oldRow)
                    oRow = []
                    kRow = []
                    for key in OLDRow.keys():
                        oRow.append(OLDRow[key])
                        kRow.append(key)
                    msgFmt = '{:12s} {:20s} {:20s} {:20s} {:16s} {:16s}'
                    for oldData, newData, key in zip(oRow, nRow, kRow):
                        newMissing = newData is None or newData == ''
                        oldMissing = oldData is None or oldData == ''
                        if oldMissing and newMissing:
                            continue
                        if newMissing:
                            update = False
                            #skip msg if more than 1 yr ago or future
                            if not (now - myDataTime > longAgo or
                                    now - myDataTime < nowDelta):
                                print(msgFmt.format(thermoName, dataTime, key,
                                                    'newData is None',
                                                    str(oldData), str(newData)))
                                print(now, myDataTime, longAgo, nowDelta,
                                      now - myDataTime,  now - myDataTime > longAgo,
                                      now - myDataTime < nowDelta)
                            continue
                        if isinstance(oldData, float):
                            try:
                                newData = float(newData)
                            except:
                                print(msgFmt.format(thermoName, dataTime, key,
                                                    'New not a float',
                                                    str(oldData), str(newData)))
                        elif isinstance(oldData, int):
                            try:
                                newData = int(newData)
                            except:
                                print(msgFmt.format(thermoName, dataTime, key,
                                                    'New not an int',
                                                    str(oldData), str(newData)))
                        if oldData == newData:
                            pass
                        else:
                            if oldMissing:
                                #print(dataTime, key, oldData, newData, 'oldData is None')
                                pass
                            else:
                                print(msgFmt.format(thermoName, dataTime, key,
                                                    'oldData <> newDatat',
                                                    str(oldData), str(newData)))
                if update:              
                    values = [dataTimetz, dataTime, temperature, humidity, desiredHeat,
                              desiredCool, hvacMode, heatPump1, heatPump2,
                              auxHeat1, auxHeat2, auxHeat3, cool1, cool2, fan,
                              outdoorHumidity, outdoorTemp, sky, wind,
                              zoneCalendarEvent, zoneClimate, zoneHvacMode, zoneOccupancy,
                              dmOffset, economizer]
                    insert = 'INSERT OR REPLACE INTO ' + table + ' (  \n' \
                        + columnNames + ')                            \n' \
                        'VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '           \
                        '       ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '           \
                        '       ?, ?, ?, ?, ?);'
                    self.c[table].execute(insert, values)
                    self.DB.commit()
                    #print(dataTimeTZ, dataTime, temperature, humidity)
                
                
                if i == 4:
                    print(dataTime, temperature, humidity, outdoorTemp,
                          zoneClimate, zoneHvacMode)

    class TZ():
        def __init__(self):
            self.last = dt.datetime(1900, 1, 1)
            self.fold = 0
            #print('TZ:__init__')

        def addTZ(self, time):
            EST5EDT = ZoneInfo('America/New_York')
            timeTZ  = time.replace(tzinfo = EST5EDT)
            if time.month == 11 and time.day < 8 and time.weekday() == 6:
                if time.hour == 1:
                    #print('TZ:addTZ handle transition')
                    if time < self.last:
                        self.fold = 1
                    timeTZ = timeTZ.replace(fold = self.fold)
                else:
                    self.fold = 0
            self.last = time
            return timeTZ
            
class ecobee(pyecobee.Ecobee):
    lastThermostats    = dt.datetime(2000, 1, 1)
    lastExtThermostats = dt.datetime(2000, 1, 1)

    def __init__(self,  config_filename: str = None, config: dict = None):
        pyecobee.Ecobee.__init__(self, config_filename = config_filename, config = config)
        self.pp = pprint.PrettyPrinter(indent=4, sort_dicts=False)
        self.debugSkip = False
        
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

    def debugThermostatSkip(self, where, now, elapsed, frequency, action):
        elapsed =  elapsed - dt.timedelta(microseconds = elapsed.microseconds)
        if self.debugSkip:
            print('ecobee:get' + where + 'ThermostatData',
                  now, ecobee.lastThermostats.replace(microsecond = 0),
                  elapsed, frequency, action)

    def getThermostatData(self, frequency = dt.timedelta(seconds = 1)):
        #print(dt.datetime.now(), 'getThermostatData')

        now = dt.datetime.now().replace(microsecond = 0)
        fudge = frequency / 10;
        elapsed = now - ecobee.lastThermostats
        if elapsed > (frequency - fudge):
            ecobee.lastThermostats = now
            self.debugThermostatSkip('', now, elapsed, frequency, 'collect')
        else:
            self.debugThermostatSkip('', now, elapsed, frequency, 'skipping')
            return

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

    def getExtThermostatData(self, frequency = dt.timedelta(seconds = 1)):
        now = dt.datetime.now().replace(microsecond = 0)
        fudge = frequency / 10;
        elapsed = now - ecobee.lastExtThermostats
        if elapsed > (frequency - fudge):
            ecobee.lastExtThermostats = now
            self.debugThermostatSkip('Ext', now, elapsed, frequency, 'collect')
        else:
            self.debugThermostatSkip('Ext', now, elapsed, frequency, 'skipping')
            return
        self.getExtThermostats()
        
    def getWeather(self, frequency):
        # rely on the data returned by getThermostatData()
        #print(dt.datetime.now(), 'getWeather')
        pass

    def getRuntimeReportData(self, startDate, endDate):
        #print('ecobee:getRuntimeReportData:', startDate, endDate)
        endDate  = endDate.isoformat()
        startDate = startDate.isoformat()
        columns = 'zoneAveTemp,zoneHumidity,zoneHeatTemp,zoneCoolTemp,hvacMode,'  +\
            'compHeat1,compHeat2,auxHeat1,auxHeat2,auxHeat3,compCool1,compCool2,' +\
            'fan,outdoorHumidity,outdoorTemp,sky,wind,zoneCalendarEvent,'         +\
            'zoneClimate,zoneHvacMode,zoneOccupancy,dmOffset,economizer'
        thermoList = list(range(len(self.thermostats)))              
        rc = self.runtimeReport(thermoList, startDate, endDate, columns = columns)
        #print('ecobee:getRuntimeReport:', startDate, endDate, rc)
        return rc
        
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
            if name == '':
                name = 'H ' + \
                    self.thermostats[index]['events'][event]['endTime'][:5]
        elif self.thermostats[index]['events'][event]['type'] == 'template':
            name = '  '
        else:
            name = 'unknown'
        if self.thermostats[index]['events'][event]['running']:
            name = '*' + name
        return name

class Status:
    def __init__(self, scheduler, thermostats = [], printer = None):
        self.scheduler   = scheduler
        self.starttime   = 0
        self.thermostats = thermostats
        self.myPrint     = printer
        self.pp = pprint.PrettyPrinter(indent=4, sort_dicts=False)
        
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
        hdr = '{:^10s} {:^8s}' \
            ' {:6s} {:4s} {:4s} {:4s} {:4s} {:3s} {:9s} {:9s} ' \
            ' {:6s} {:4s} {:4s} {:4s} {:4s} {:3s} {:9s} {:9s}'

        line = hdr.format('Date', 'Time',
                          'Thermo', 'Temp', 'Hum.', 'Heat', 'Cool', 'Act', 'Event0', 'Event1',
                          'Thermo', 'Temp', 'Hum.', 'Heat', 'Cool', 'Act', 'Event0', 'Event1')
        self.myPrint.Print(line + '\n')

    def addLine(self, note):
        self.printStatusLine(note = note, reschedule = False)

    def equipmentStatus(self, i):
        eStat = self.API.thermostats[i]['equipmentStatus']
        stat = ''
        eStats = ['compCool', 'heatPump', 'auxHeat', 'fan']
        shortStats = ['C', 'H', 'A', 'F']
        for long, short in zip(eStats, shortStats):
            if long in eStat:
                stat += short
        # NC gas heat shoiws as aux
        if 'A' in stat and 'H' not in stat:
            stat.replace('A', 'H')
        return stat
        
    def printStatusLine(self, note = '', reschedule = True):
        #self.dump()
        self.starttime = self.starttime + self.frequency
        if reschedule:
            self.scheduler.enterabs(time.mktime(self.starttime.timetuple()), 1, self.Printer, ())
        if self.API.thermostats is None:
            # wait for initialization
            return
        fmt = '{:^6s} {:4.1f} {:^4d} {:4.1f} {:4.1f} {:^3s} {:^9s} {:^9s}  '
        fmt = '{:17s} ' + fmt + fmt + ' {:s}'
        now = dt.datetime.now().replace(microsecond = 0)
        Name = [[]]
        # fill the array in case there is only the "template" event
        for i in range(len(self.API.thermostats)):
            Name.append([])
            for j in range(2):
                Name[i].append('   ')
        # There may be 3 or more events. E.g. vacation, climate hold, template
        myTherms = []
        myEquipStat = []
        #self.pp.pprint(Name)
        for i in range(len(self.API.thermostats)):
            if self.API.thermostats[i]['name'] not in self.thermostats:
                #print('SSS Skipping:',  self.API.thermostats[i]['name'])
                continue
            myTherms.append(i)
            '''
            if i > 1:
                Name.append([])
            '''
            for j in range(len(self.API.thermostats[i]['events'])):
                #print('MMM', i, j, self.API.getCurrentMode(i, j))
                try:
                    if j > 1:
                        Name[i].append(self.API.getCurrentMode(i, j))
                    else:
                        Name[i][j] = (self.API.getCurrentMode(i, j))
                except:
                    print(i, j, Name)
                    pp = pprint.PrettyPrinter(indent=4, sort_dicts=False)
                    pp.pprint(self.API.thermostats)
            myEquipStat.append(self.equipmentStatus((i)))
        #print('sss myTherms:', myTherms)
        (A, B) = myTherms
        #self.pp.pprint(Name)
        line = fmt.format(str(now),
                          self.API.thermostats[A]['name'].replace('stairs', '').replace('Room', ''),
                          self.API.thermostats[A]['runtime']['actualTemperature'] / 10.0,
                          self.API.thermostats[A]['runtime']['actualHumidity'],
                          self.API.thermostats[A]['runtime']['desiredHeat'] / 10.0,
                          self.API.thermostats[A]['runtime']['desiredCool'] / 10.0,
                          myEquipStat[0],
                          Name[A][0],
                          Name[A][1],
                          self.API.thermostats[B]['name'].replace('stairs', '').replace('Room', ''),
                          self.API.thermostats[B]['runtime']['actualTemperature'] / 10.0,
                          self.API.thermostats[B]['runtime']['actualHumidity'],
                          self.API.thermostats[B]['runtime']['desiredHeat'] / 10.0,
                          self.API.thermostats[B]['runtime']['desiredCool'] / 10.0,
                          myEquipStat[1],
                          Name[B][0],
                          Name[B][1],
                          note
                          )
        self.myPrint.Print(line + '\n')
        
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
        self.backupMode = backupMode()
        self.DebugRuntSch = True
        
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
        if self.backupMode.active():
            print('backupMode.active: skipping Collector')
            return
        self.Getter(frequency = self.frequency)
        self.Saver(self.API)

    def debugRuntSch(self, caption, ev):
        if self.DebugRuntSch:
            print(caption, dt.datetime.fromtimestamp(ev.time),
                  str(ev.action).split(' ')[2], ev.argument)

    def runTSchedule(self, Getter, Saver, API, dataDays = 1,  dayOfMonth = None,
                     hour = 0, minute = 0, days = 0, hours = 0, minutes = 0,
                     seconds = 0):
        self.frequency = dt.timedelta(days = days, hours = hours,
                                      minutes = minutes, seconds = seconds)
        self.Getter     = Getter
        self.Saver      = Saver
        self.API        = API
        self.dayOfMonth = dayOfMonth
        self.startDate  = None
        self.hour       = hour
        self.minute     = minute
        now = dt.datetime.now()
        print(self.dayOfMonth, dayOfMonth, dataDays)
        if self.dayOfMonth == None:
            firstTime = now.replace(hour = self.hour, minute = self.minute,
                                    second = 0, microsecond = 0) - \
                                    dt.timedelta(weeks = 1)
            while firstTime < now:
                firstTime += self.frequency
        else:
            self.frequency = dt.timedelta(days = 28)   # not needed?
            firstTime = now.replace(day = self.dayOfMonth,
                                    hour = self.hour, minute = self.minute,
                                    second = 0, microsecond = 0) - \
                                    relativedelta(months = 1)
            while firstTime < now:
                firstTime += relativedelta(months = 1)
        self.starttime = firstTime
        print('Schedule Start time:', self.starttime, dataDays)
        ev = self.scheduler.enterabs(time.mktime(self.starttime.timetuple()), 1,
                                    self.runTCollector, (dataDays,))
        self.debugRuntSch('runTSchedule:first event:', ev)
            
    def runTCollector(self, dataDays):
        MaxReqDays  = 7
        maxReqDays  = dt.timedelta(days = MaxReqDays - 1)
        pause       = dt.timedelta(seconds = 11)
        oneDay      = dt.timedelta(days = 1)
        installDate = dt.date(2021, 3, 1)
        oldestData  = dt.date(2023, 2, 1)
        dashes      = '*********************'
        # reschedule
        if self.dayOfMonth == None:
            self.starttime += self.frequency
        else:
            self.starttime += relativedelta(months = 1)

        ev = self.scheduler.enterabs(time.mktime(self.starttime.timetuple()), 1,
                                     self.runTCollector, argument = (dataDays,))
        self.debugRuntSch('runTCollector: next event:', ev)

        if self.backupMode.active():
            print('backupMode.active: skipping Collector')
            return
        
        if self.startDate is None:
            self.startDate   = dt.date.today() - dt.timedelta(days = dataDays)
            self.endDate = None
        if dataDays <= MaxReqDays:
            self.endDate = self.startDate + dt.timedelta(days = dataDays)
            print('runTCollector:endDate:X:', self.startDate, self.endDate, dataDays)
            self.Getter(self.startDate, self.endDate)
            self.Saver(self.API, self.startDate, self.endDate)
            self.endDate = self.startDate = None
            print('runTCollector:MaxReqDays loop done')
            #z = dataDays / 0
        else:
            if self.endDate is None:
                self.endDate = self.startDate + maxReqDays
                print('runTCollector:endDate:Z:', self.startDate, self.endDate, dataDays)
            else:
                self.startDate = self.endDate + oneDay
                self.endDate = self.startDate + maxReqDays
            #print('runTCollector:endDate:Z:', self.startDate, self.endDate, dataDays)
            if self.endDate < installDate or self.endDate < oldestData:
                dashes1 = '\n' + dashes
                dashes2 =  dashes + '\n'
                eDate   = str(self.endDate)
                if self.endDate < installDate:
                    print(dashes1 + eDate + ' Prior to EcoBee install ' + dashes2)
                if self.endDate < oldestData:
                    print(dashes1 + eDate + ' Prior to Oldest EcoBee Data ' + dashes2)
            else:
                self.Getter(self.startDate, self.endDate)
                self.Saver(self.API, self.startDate, self.endDate)
            self.starttime = dt.datetime.now() + pause
            dataDays -= MaxReqDays
            self.startDate += dt.timedelta(days = MaxReqDays)
            ev = self.scheduler.enterabs(time.mktime(self.starttime.timetuple()), 1,
                                         self.runTCollector, (dataDays,))
            self.debugRuntSch('runTCollector:MaxReqDays loop next:', ev)
        
class deHumidify:
    def __init__(self, scheduler, thermostats = [], where = 'noWhere'):
        self.scheduler = scheduler
        self.where     = where
        self.starttime = 0
        self.thermostats = thermostats
        self.backupMode = backupMode()
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

        if self.backupMode.active():
            print('backupMode.active: skipping forceRun')
            return

        for i in range(len(self.API.thermostats)):
            if self.API.thermostats[i]['name'] not in self.thermostats:
                continue
            events = [self.API.getCurrentMode(i, 0), self.API.getCurrentMode(i, 1)]
            if '*vacation' not in events[0] and '*vacation' not in events[1]:
                print('thermostat', i, self.API.thermostats[i]['name'],
                      'not running in vacation mode')
                print(events)
                return

        icebox = 'smart1'
        oven   = 'smart2'
        indoorTemp  = 0.0
        outdoorHigh = 0.0
        myThermos = []
        for i in range(len(self.API.thermostats)):
            if self.API.thermostats[i]['name'] not in self.thermostats:
                continue
            myThermos.append(i)
            indoorTemp  += self.API.thermostats[i]['runtime']['actualTemperature']
            outdoorHigh += self.API.thermostats[i]['weather']['forecasts'][0]['tempHigh']
        indoorTemp  = indoorTemp  / 10.0 / len(myThermos)
        outdoorHigh = outdoorHigh / 10.0 / len(myThermos)
        if indoorTemp >= 65 and outdoorHigh > 70.0:
            climate = icebox
        else:
            climate = oven
        note = 'inTemp: {:4.1f} outHigh: {:4.1f} climate: {:s}'.format(indoorTemp,
                                                                       outdoorHigh,
                                                                       climate)
        self.Status(note)
        finish = dt.datetime.now() + dt.timedelta(minutes = self.duration)

        for i in myThermos:
            self.API.Set_Climate_hold(index = i,
                                      climate   = climate,
                                      hold_type = 'dateTime',
                                      end_date  = str(finish.date()),
                                      end_time  = str(finish.time())[0:8]
                                      )
            time.sleep(5)
        time.sleep(10)
        self.API.getThermostatData()
        self.debugVacation(myThermos, hdr = 'after adding climate hold')
        self.Status('deHumidify: climate hold added')
        #self.pp.pprint(self.API.thermostats)

    def debugVacation(self, Thermos, hdr = 'no header'):
        print('debugVacation: ', hdr)
        for i in Thermos:
            self.pp.pprint(self.API.thermostats[i]['name'])
            self.pp.pprint(self.API.thermostats[i]['events'])

class TimeOfUse:
    def __init__(self, scheduler, HVACnode, thermostats = [], printer = None):
        self.scheduler   = scheduler
        self.thermostats = thermostats
        self.myPrint     = printer
        self.normalModes = HVACnode
        self.modeOff     = 'off'
        self.modeNormal  = []

    def setDates(self, startMonth = 1, startDay = 2, endMonth = 3, endDay = 4):
        self.startMonth = startMonth
        self.startDay   = startDay
        self.endMonth   = endMonth
        self.endDay     = endDay
        print('TimeOfUse.setDates', startMonth, startDay, endMonth, endDay)
        
    def setFirst(self, startHour, startMinute, modeSet, mode = None):
        now = dt.datetime.now()
        firstTime = now.replace(hour = startHour, minute = startMinute,
                                second = 0, microsecond = 0) - dt.timedelta(days = 1)
        while firstTime < now:
            firstTime += dt.timedelta(days = 1)
        self.scheduler.enterabs(time.mktime(firstTime.timetuple()), 1, modeSet, ())
        if mode == 'normal':
            print('setFirst:Normal', self.modeNormal, firstTime)
            self.normalTime = firstTime
        elif mode == 'off':
            print('setFirst:off:', self.modeOff, firstTime)
            self.offTime = firstTime
        else:
            print('TimeOfUse.setFirst unknow mode', mode)

    def checkActiveSeason(self):
        now = dt.datetime.now()
        startTime = dt.datetime(now.year, self.startMonth, self.startDay)
        endTime   = dt.datetime(now.year, self.endMonth,   self.endDay) - \
            dt.timedelta(minutes = 2)
        print('checkActiveSeason', startTime, endTime, now)
        if endTime < startTime:
            endTime += relativedelta(years = 1)
            print('checkActiveSeason', startTime, endTime, now)
        if startTime <= now <= endTime:
            print('Active')
            return True
        else:
            print('InActive')
            return False

    def checkActiveOffTime(self):
        now = dt.datetime.now()
        startTime = dt.datetime(now.year, now.month, now.day, \
                                hour = self.offHour,    minute = self.offMinute)
        endTime   = dt.datetime(now.year, now.month, now.day, \
                                hour = self.normalHour, minute = self.normalMinute) - \
                                dt.timedelta(minutes = 2)
        print('checkActiveOffTime', startTime, endTime, now, now > startTime, now < endTime)
        if startTime <= now <= endTime:
            print('checkActiveOffTime: True')
            return True
        else:
            print('checkActiveOffTime: False')
            return False

    def setModeOff(self):
        if not self.checkActiveSeason():
            return
        if not self.checkActiveOffTime():
            return
        self.offTime += dt.timedelta(days = 1)
        self.scheduler.enterabs(time.mktime(self.offTime.timetuple()), 1,
                                self.setModeOff, ())
        for i in range(len(self.API.thermostats)):
            if self.API.thermostats[i]['name'] in self.thermostats:
                self.setMode(self.modeOff, i)
                print('setModeOff:', self.API.thermostats[i]['name'])

    def setModeNormal(self):
        print('setModeNormal')
        if not self.checkActiveSeason():
            return
        self.normalTime += dt.timedelta(days = 1)
        self.scheduler.enterabs(time.mktime(self.normalTime.timetuple()), 1,
                                self.setModeNormal, ())
        modes = self.normalModes.get()
        for i in range(len(self.API.thermostats)):
            if self.API.thermostats[i]['name'] in self.thermostats:
                mode = modes.get(self.API.thermostats[i]['name'], None)
                if mode is not None:
                    self.setMode(mode, i)
                    print('setModeNormal:', self.API.thermostats[i]['name'], mode)
                else:
                    print('setModeNormal', self.API.thermostats[i]['name'],
                          'not found', modes)

    def Schedule(self, API, offHour = 15, offMinute = 0, normalHour = 18, normalMinute = 0):
        self.offHour      = offHour
        self.offMinute    = offMinute
        self.normalHour   = normalHour
        self.normalMinute = normalMinute
        self.API = API
        self.setFirst(offHour,    offMinute,    self.setModeOff,    mode = 'off')
        self.setFirst(normalHour, normalMinute, self.setModeNormal, mode = 'normal')
        #self.getNormalMode()
        self.setModeOff()     # set "off" - check first

    def setMode(self, mode, i):
        print('setMode', mode, i, self.API.thermostats[i]['name'], dt.datetime.now())
        self.API.set_hvac_mode(i, mode)
        
def main():
    pp = pprint.PrettyPrinter(indent=4, sort_dicts=False)
    #config = {'API_KEY' : 'ObsoleteAPIkey', 'INCLUDE_NOTIFICATIONS' : 'True'}
    #API = pyecobee.Ecobee(config = config)
    API = ecobee(config_filename = 'ecobee.conf')
    setLogging(pyecobee._LOGGER)
    API.read_config_from_file()
    NCthermostats = ['Loft', 'LivingRoom']
    SCthermostats = ['Upstairs', 'Downstairs']
    Allthermostats = NCthermostats + SCthermostats
    # intialize API.thermostats
    API.getThermostatData()
    
    HVACmode = normalTermostatModes()
    NCsave = saveEcobeeData(HVACmode, thermostats = NCthermostats, where = 'NC')
    SCsave = saveEcobeeData(HVACmode, thermostats = SCthermostats, where = 'SC')
    rRsave = saveEcobeeData(HVACmode, thermostats = Allthermostats, where = 'All')
    HVACmode.getSaved(SCsave.getSavedHVACmodes)

    # Build a scheduler object that will look at absolute times
    scheduler = sched.scheduler(time.time, time.sleep)

    NCruntime = collectThermostatData(scheduler)
    SCruntime = collectThermostatData(scheduler)
    NCruntime.Schedule(API.getThermostatData, NCsave.ThermostatData, API, minutes = 2, seconds = 45)
    SCruntime.Schedule(API.getThermostatData, SCsave.ThermostatData, API, minutes = 2, seconds = 45)
    
    NCextRuntime = collectThermostatData(scheduler)
    SCextRuntime = collectThermostatData(scheduler)
    NCextRuntime.Schedule(API.getExtThermostatData, NCsave.ExtRuntimeData, API, minutes = 12)
    SCextRuntime.Schedule(API.getExtThermostatData, SCsave.ExtRuntimeData, API, minutes = 12)
    
    NCweather = collectThermostatData(scheduler)
    SCweather = collectThermostatData(scheduler)
    NCweather.Schedule(API.getWeather, NCsave.WeatherData, API, minutes = 25)
    SCweather.Schedule(API.getWeather, SCsave.WeatherData, API, minutes = 25)
    
    rR2Hourly = collectThermostatData(scheduler)
    rR2Hourly.runTSchedule(API.getRuntimeReportData, rRsave.RuntimeReportData,
                           API, hours = 2, dataDays = 0)
    rRDaily   = collectThermostatData(scheduler)
    rRDaily.runTSchedule(API.getRuntimeReportData, rRsave.RuntimeReportData,
                         API, days = 1, hour = 3, dataDays = 1)
    rRWeekly  = collectThermostatData(scheduler)
    rRWeekly.runTSchedule(API.getRuntimeReportData, rRsave.RuntimeReportData,
                          API, days = 7, hour = 3, dataDays = 15)
    rRmonthly = collectThermostatData(scheduler)
    rRmonthly.runTSchedule(API.getRuntimeReportData, rRsave.RuntimeReportData,
                           API, dayOfMonth = 8, hour = 3, minute = 7,
                           dataDays = 600)

    NCprint  = fdPrint(7)
    SCprint  = fdPrint(8)
    
    NCheader = Status(scheduler, thermostats = NCthermostats, printer = NCprint)
    SCheader = Status(scheduler, thermostats = SCthermostats, printer = SCprint)

    NCheader.Schedule(API, NCheader.printHeaderLine, minutes = 40)
    SCheader.Schedule(API, SCheader.printHeaderLine, minutes = 40)

    NCstatus = Status(scheduler, thermostats = NCthermostats, printer = NCprint)
    SCstatus = Status(scheduler, thermostats = SCthermostats, printer = SCprint)
    NCstatus.Schedule(API, NCstatus.printStatusLine, minutes = 3)
    SCstatus.Schedule(API, SCstatus.printStatusLine, minutes = 3)

    NCdehumidify = deHumidify(scheduler, thermostats = NCthermostats, where = 'NC')
    SCdehumidify = deHumidify(scheduler, thermostats = SCthermostats, where = 'SC')

    host = os.getenv('HOSTNAME')
    if host == 'jim4':
        NCdehumidify.Schedule(API, NCstatus.addLine, startHour = 6,
                              startMinute = 30, duration = 60)
        SCdehumidify.Schedule(API, SCstatus.addLine, startHour = 4,
                              startMinute = 45, duration = 60)
    else:
        # if not tunning at "home", set start 5 minutes later
        # should allow home to disable vacation mode, if it is running
        NCdehumidify.Schedule(API, NCstatus.addLine, startHour = 6,
                              startMinute = 35, duration = 60)
        SCdehumidify.Schedule(API, SCstatus.addLine, startHour = 4,
                              startMinute = 50, duration = 60)
    
    SCTimeOfUseSummer = TimeOfUse(scheduler, HVACmode, thermostats = SCthermostats,
                                  printer = SCprint)
    SCTimeOfUseSummer.setDates(startMonth = 4, startDay = 1, endMonth = 10,
                               endDay = 31)
    if True:
        SCTimeOfUseSummer.Schedule(API, offHour = 15, offMinute = 0,
                                   normalHour = 18, normalMinute = 0)
    else:
        S = E = dt.datetime.now()
        S = S + dt.timedelta(minutes = 5)
        E = E + dt.timedelta(minutes = 20)
        SCTimeOfUseSummer.Schedule(API, offHour = S.hour , offMinute = S.minute ,
                                   normalHour = E.hour , normalMinute = E.minute)

    SCTimeOfUseWinter = TimeOfUse(scheduler, HVACmode, thermostats = SCthermostats,
                                  printer = SCprint)
    SCTimeOfUseWinter.setDates(startMonth = 11, startDay = 1, endMonth = 3, endDay = 31)
    SCTimeOfUseWinter.Schedule(API, offHour = 6, offMinute = 0, normalHour = 9,
                               normalMinute = 0)

    ###############3 debug
    '''
    DH = dt.datetime.now().replace(microsecond = 0) + dt.timedelta(minutes = 10)
    NCdehumidify.Schedule(API, NCstatus.addLine, startHour = DH.hour,
                          startMinute = DH.minute, duration = 30)
    SCdehumidify.Schedule(API, SCstatus.addLine, startHour = DH.hour,
                          startMinute = DH.minute, duration = 30)
    '''
    ###############
    
    print(len(scheduler.queue))
    #print(scheduler.queue)
    for event in scheduler.queue:
        print(dt.datetime.fromtimestamp(event.time), str(event.action).split(' ')[2],
              event.argument)
    print('\n\n')
    NCheader.printHeaderLine(reschedule = False)
    SCheader.printHeaderLine(reschedule = False)

    scheduler.run()

if 'New' in sys.argv[0]:
    DBname  = '/home/jim/tools/Ecobee/Thermostats.New.sql'
    LOGFILE = '/home/jim/tools/Ecobee/ecobee.New.log'
else:
    DBname  = '/home/jim/tools/Ecobee/Thermostats.sql'
    LOGFILE = '/home/jim/tools/Ecobee/ecobee.log'

if __name__ == '__main__':
    # want unbuffered stdout for use with "tee"
    buffered = os.getenv('PYTHONUNBUFFERED')
    if buffered is None:
        myenv = os.environ.copy()
        myenv['PYTHONUNBUFFERED'] = 'Please'
        os.execve(sys.argv[0], sys.argv, myenv)
    main()
