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
import time
import os
import sys
from traceback import print_exc


def findSubstr(s1, s2):
    l = s1.split(',')
    for i in range(len(l)):
        if l[i].lower().find(s2) != -1:
            return l[i]
    return None


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
        
def main():
    pp = pprint.PrettyPrinter(indent=4, sort_dicts=False)
    #config = {'API_KEY' : 'ObsoleteAPIkey', 'INCLUDE_NOTIFICATIONS' : 'True'}
    #API = pyecobee.Ecobee(config = config)
    API = ecobee(config_filename = 'ecobee.conf')
    API.read_config_from_file()
    # intialize API.thermostats
    API.getThermostatData()
    for i in reversed(range(len(API.thermostats))):
        if API.thermostats[i]['name'] != 'Downstairs':
            del API.thermostats[i]
        else:
            del API.thermostats[i]['notificationSettings']
            del API.thermostats[i]['program']
            del API.thermostats[i]['settings']
            del API.thermostats[i]['runtime']
            del API.thermostats[i]['weather']
            del API.thermostats[i]['remoteSensors']
    pp.pprint(API.thermostats)



if __name__ == '__main__':
    # want unbuffered stdout for use with "tee"
    buffered = os.getenv('PYTHONUNBUFFERED')
    if buffered is None:
        myenv = os.environ.copy()
        myenv['PYTHONUNBUFFERED'] = 'Please'
        os.execve(sys.argv[0], sys.argv, myenv)
    main()
