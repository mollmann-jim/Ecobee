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
            
        
def main():
    pp = pprint.PrettyPrinter(indent=4, sort_dicts=False)
    #config = {'API_KEY' : 'ObsoleteAPIkey', 'INCLUDE_NOTIFICATIONS' : 'True'}
    #API = pyecobee.Ecobee(config = config)
    API = pyecobee.Ecobee(config_filename = 'ecobee.conf')
    setLogging(pyecobee._LOGGER)
    API.read_config_from_file()
    #umpEcobee(API)

    if API.access_token is None:
        rc = API.request_pin()
        print('request pin:', rc, ' PIN:', API.pin)
        rc = getTokens(API)
        print('get tokens:', rc)
        dumpEcobee(API)
        API._write_config()
    #API.include_notifications = False
    rc = False
    try:
        rc = API.get_thermostats()
    
    except pyecobee.errors.ExpiredTokenError as e:
        print('type is:', e.__class__.__name__)
        print_exc()
        print('YYYY')
        rc = API.refresh_tokens()
        if rc:
            API._write_config()
            rc = API.get_thermostats()
            if not rc:
                print('get_thermostats() failed again')

    #print('thermostats:')
    #pp.pprint(API.thermostats)
    for i in range(len(API.thermostats)):
        print(API.thermostats[i]['name'], \
              API.thermostats[i]['runtime']['actualTemperature'] / 10.0, \
              API.thermostats[i]['runtime']['actualHumidity'])



if __name__ == '__main__':
  main()
