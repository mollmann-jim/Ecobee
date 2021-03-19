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
from traceback import print_exc

def setLogging(logger):
    logger.setLevel(logging.DEBUG)
    # create file handler which logs even debug messages
    fh = logging.FileHandler('ecobee.log')
    fh.setLevel(logging.ERROR)
    fh.setLevel(logging.DEBUG)
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

def dumpEcobee(API):
    print('thermostats:', API.thermostats)
    print('config_file:', API.config_filename)
    print('config:', API.config)
    print('api_key:', API.api_key)
    print('pin:', API.pin)
    print('.authorization_code:', API.authorization_code)
    print('access_token:', API.access_token)
    print('refresh_token:', API.refresh_token)

def findSubstr(s1, s2):
    l = s1.split(',')
    for i in range(len(l)):
        if l[i].lower().find(s2) != -1:
            return l[i]
    return None

def getTokens(API):
    attempts = 32
    delay = 30
    for attempt in range(attempts):
        rc = API.request_tokens()
        if rc:
            print('attempt:', attempt, 'Got tokens')
            return True
        else:
            print('attempt:', attempt, 'Failed to get tokens')
            time.sleep(delay)
    return False

def getThermostatData(API):
    if API.access_token is None:
        rc = API.request_pin()
        print('request pin:', rc, ' PIN:', API.pin)
        rc = getTokens(API)
        print('get tokens:', rc)
        dumpEcobee(API)
        API._write_config()
    
    try:
        rc = API.get_thermostats()
    
    except pyecobee.errors.ExpiredTokenError as e:
        #print('type is:', e.__class__.__name__)
        #print_exc()
        #print('YYYY')
        rc = API.refresh_tokens()
        if rc:
            API._write_config()
            rc = API.get_thermostats()
            if not rc:
                print('get_thermostats() failed again')

    #print('thermostats:')
    #pp.pprint(API.thermostats)

def saveThermostatData(API, DB, c):
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
        coolStatus = heatStatus = fanOn = holdStatus = holdUntil = 'junk data'
        statusTime = dt.datetime.strptime(API.thermostats[i]['runtime']['lastStatusModified']
                                          + ' UTC', '%Y-%m-%d %H:%M:%S %Z')
        statusTime = statusTime.astimezone(tz = tz.gettz('NewYork'))
        coolStatus = findSubstr(API.thermostats[i]['equipmentStatus'], 'cool')
        heatStatus = findSubstr(API.thermostats[i]['equipmentStatus'], 'heat')
        fanOn      = 'on' if findSubstr(API.thermostats[i]['equipmentStatus'], 'fan') == 'fan' else 'off'
        holdUntil = API.thermostats[i]['events'][0]['endDate'] + ' ' + \
            API.thermostats[i]['events'][0]['endTime']       
        if API.thermostats[i]['events'][0]['type'] == 'hold':
            holdStatus = 'hold'
        elif API.thermostats[i]['events'][0]['type'] == 'vacation':
            holdStatus = 'vacation'
        else:
            holdStatus = holdUntil = None
        c[table].execute(insert, [statusTime, \
                                 API.thermostats[i]['runtime']['actualTemperature'] / 10.0, \
                                 API.thermostats[i]['runtime']['actualHumidity'], \
                                 API.thermostats[i]['runtime']['desiredCool'] /10.0, \
                                 API.thermostats[i]['runtime']['desiredHeat'] /10.0, \
                                 coolStatus, \
                                 heatStatus, \
                                 API.thermostats[i]['runtime']['desiredFanMode'], \
                                 fanOn, \
                                 API.thermostats[i]['settings']['hvacMode'], \
                                 API.thermostats[i]['program']['currentClimateRef'], \
                                 holdStatus, \
                                  holdUntil])
        DB.commit()
        
def main():
    DBname = '/home/jim/tools/Ecobee/MBthermostat.sql'
    DB = sqlite3.connect(DBname)
    DB.row_factory = sqlite3.Row
    c = {}
    for table in ['Upstairs', 'Downstairs']:
        c[table] = DB.cursor()
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
        c[table].execute(create)
        
    pp = pprint.PrettyPrinter(indent=4, sort_dicts=False)
    #config = {'API_KEY' : 'ObsoleteAPIkey', 'INCLUDE_NOTIFICATIONS' : 'True'}
    #API = pyecobee.Ecobee(config = config)
    API = pyecobee.Ecobee(config_filename = 'ecobee.conf')
    setLogging(pyecobee._LOGGER)
    API.read_config_from_file()
    #umpEcobee(API)

    while True:
        getThermostatData(API)
        saveThermostatData(API, DB, c)
        time.sleep(179)





if __name__ == '__main__':
  main()
