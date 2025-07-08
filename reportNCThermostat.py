#!/usr/bin/env python3
import datetime as dt
import sqlite3
from dateutil.tz import tz
from sys import path
import os

home = os.getenv('HOME')

path.append(home + '/tools/')
from shared import getTimeInterval

#DBname = home + '/tools/Honeywell/MBthermostat3.sql'
saneUsageMax = 33.3
#saneUsageMax = 10.0
global insaneUsage
insaneUsage = ''

def fmtTempsLine(tag, row):
    #print(tag, row['minT'],row['maxT'],row['avgT'],row['minC'],row['maxC'],row['avgC'],
    #      row['minH'],row['maxH'],row['avgH'])
    noData = '  None'
    noData = '     .'
    line = tag + ': (none)'
    if row['minT'] is not None:
        period =  '{:>10s}'.format(tag)
        minT   = ' {:>5.1f}'.format(row['minT'])     if row['minT'] is not None else noData
        maxT   = ' {:>5.1f}'.format(row['maxT'])     if row['maxT'] is not None else noData
        avgT   = ' {:>5.1f}'.format(row['avgT'])     if row['avgT'] is not None else noData
        minC   = ' {:>-5d}'.format(int(row['minC'])) if row['minC'] is not None else noData
        maxC   = ' {:>5d}'.format(int(row['maxC']))  if row['maxC'] is not None else noData
        avgC   = ' {:>5.1f}'.format(row['avgC'])     if row['avgC'] is not None else noData
        minH   = ' {:>5d}'.format(int(row['minH']))  if row['minH'] is not None else noData
        maxH   = ' {:>5d}'.format(int(row['maxH']))  if row['maxH'] is not None else noData
        avgH   = ' {:>5.1f}'.format(row['avgH']) if row['avgH'] is not None else noData
        line = period + minT + maxT + avgT + minC + maxC + avgC + minH + maxH + avgH
    return line

def fmtRunTmLine(x):
    
    line = ''
    noData = '     .'
    if x['elapsed'] > 0:
        heatPct = '{:>6.1f}'.format(100.0 * x['heat']  / x['elapsed']) \
            if x['heat']  is not None else noData
        coolPct = '{:>6.1f}'.format(100.0 * x['cool']  / x['elapsed']) \
            if x['cool']  is not None else noData
        fanPct  = '{:>6.1f}'.format(100.0 * x['fanOn'] / x['elapsed']) \
            if x['fanOn'] is not None else noData
        line = heatPct + coolPct + fanPct
    return line

def printHeader():
    #      2020/07/02 ttttt TTTTT aaaaa ccccc CCCCC aaaaa hhhhh HHHHH aaaaahhhhhhccccccffffff
    print('')
    print('                               Min   Max   Avg   Min   Max   Avg  Heat  Cool   Fan')
    print('             Min   Max   Avg  Cool  Cool  Cool  Heat  Heat  Heat   Run   Run   Run')
    print('            Temp  Temp  Temp   Set   Set   Set   Set   Set   Set     %     %     %')

 
def adapt_datetime(dt):
    #print('adapt_datetime', dt, dt.isoformat(sep=' '))
    return dt.isoformat(sep=' ')

def convert_datetime(val):
    #print('convert_datetime', val, dt.datetime.fromisoformat(val).replace('T', ' '))
    return dt.datetime.fromisoformat(val).replace('T', ' ')

def checkSanity(runStats, date, where):
    global insaneUsage
    # do not flag old usage
    now = dt.datetime.now()
    date = dt.datetime.strptime(date, '%Y-%m-%d')
    if (now - date) > dt.timedelta(days = 31):
        return False
    for which in ['heat', 'cool', 'fanOn']:
        if runStats[which] is not None:
            runPct = 100.0 * runStats[which] / runStats['elapsed']
            if runPct > saneUsageMax:
                fmt = '\n{:>10s} - {:>10s} {:>4s} utilization of {:>5.1f}% exceeds the {:>5.1f}%' \
                    ' limit. Runtime = {:>8s}'
                runTime = str(dt.timedelta(seconds = runStats[which]))
                insaneUsage += fmt.format(date, where, which, runPct, saneUsageMax, runTime)
                return True
    return False
                                               
def runTimes(c, table, start, end, fanTime, auxTime):
    selectTime = 'SELECT min(dataTime) as first, max(dataTime) as last '\
        ' FROM ' + table +\
        ' WHERE dataTime >= ? AND dataTime <= ?'
    c.execute(selectTime, (start, end))
    result = c.fetchone()
    if result['first'] is None or result['last'] is None:
        return {'elapsed' : 0, 'heat' : 0, 'cool' : 0, 'fanOn': fanTime}
    '''
    first = dt.datetime.strptime(result['first'], '%Y-%m-%d %H:%M:%S%z')
    last  = dt.datetime.strptime(result['last'],  '%Y-%m-%d %H:%M:%S%z')
    '''
    first = dt.datetime.fromisoformat(result['first'])
    last  = dt.datetime.fromisoformat(result['last'])
    ###print('runTimes: first, last', first, last)
    selectHeat = 'SELECT sum(auxHeat1) as heat FROM ' + table +\
        ' WHERE dataTime >= ? AND dataTime <= ? AND hvacMode = "heatStage1On";'
    ###print('runTimes: start, end', start, end)
    c.execute(selectHeat, (start, end))
    result = c.fetchone()
    if result is None:
        heatTime = 0
    else:
        heatTime = result['heat']
    selectCool = 'SELECT sum(cool1) as cool FROM ' + table +\
        ' WHERE dataTime >= ? AND dataTime <= ? AND hvacMode = "compressorCoolStage1On";'
    c.execute(selectCool, (start, end))
    result = c.fetchone()
    if result is None:
        cool = 0
    else:
        coolTime = result['cool']
    elapsed = (last - first).total_seconds()
    ###print('runTimes: first, last, elapsed',first, last, elapsed)
    return {'elapsed' : elapsed, 'heat' : heatTime, 'cool' : coolTime, 'fanOn': fanTime}

def getYears(c, table):
    select_min_max_yr = 'SELECT '\
        'min(dataTime) AS min,  '\
        'max(dataTime) AS max   '\
        'FROM ' + table + ';'
    c.execute(select_min_max_yr)
    minmax = c.fetchone()
    #print('getYears:', minmax['min'], minmax['max'])
    '''
    first = dt.datetime.strptime(minmax['min'], '%Y-%m-%d %H:%M:%S%z')
    last  = dt.datetime.strptime(minmax['max'], '%Y-%m-%d %H:%M:%S%z')
    '''
    first = dt.datetime.fromisoformat(minmax['min'])
    last  = dt.datetime.fromisoformat(minmax['max'])
    return first, last

def makeSection(c, thermostat, table, title, byDay = False, byMonth = False, year = None):
    start, end, name = getTimeInterval.getPeriod(title, year = year)
    selectFields = 'SELECT '           \
        'date(dataTime)    AS date,   '\
        'max(temperature)  AS maxT,   '\
        'min(temperature)  AS minT,   '\
        'avg(temperature)  AS avgT,   '\
        'max(desiredCool)  AS maxC,   '\
        'min(desiredCool)  AS minC,   '\
        'avg(desiredCool)  AS avgC,   '\
        'max(desiredHeat)  AS maxH,   '\
        'min(desiredHeat)  AS minH,   '\
        'avg(desiredHeat)  AS avgH,   '\
        'sum(fan)          AS fanRun, '\
        'sum(auxHeat1)     AS auxRun  '\
        ' FROM ' + table +\
        ' WHERE dataTime >= ? AND dataTime <= ? '
    select = selectFields + ' ;'
    # sqlite date(timestamp) returns the UTC date
    selectByDay   = selectFields + ' GROUP BY substr(dataTime,1,10) ORDER BY dataTime DESC;'
    selectByMonth = selectFields + ' GROUP BY substr(dataTime,1, 7) ORDER BY dataTime DESC;'
    if byDay:
        c.execute(selectByDay, (start, end))
    elif byMonth:
        c.execute(selectByMonth, (start, end))
    else:
        c.execute(select, (start, end))
    result = c.fetchall()
    for record in result:
        if byDay:
            lineTemps = fmtTempsLine(record['date'], record)
            BOD = dt.datetime.combine(dt.datetime.strptime(record['date'], '%Y-%m-%d').date(), \
                                      dt.time.min)
            EOD = dt.datetime.combine(dt.datetime.strptime(record['date'], '%Y-%m-%d').date(), \
                                      dt.time.max)
            ###print('byDay: date,BOD,EOD', record['date'], BOD, EOD )
            dailyRunStats = runTimes(c, table, BOD, EOD, record['fanRun'], record['auxRun'])
            ###print(dailyRunStats, title)
            lineRunTm = fmtRunTmLine(dailyRunStats)
            if checkSanity(dailyRunStats, record['date'], thermostat):
                lineRunTm += ' High Usage'
        elif byMonth:
            lineTemps = fmtTempsLine(record['date'][0:7], record)
            BOM = dt.datetime.combine(dt.datetime.strptime(record['date'], '%Y-%m-%d').date(), \
                                      dt.time.min)
            BOM = BOM.replace(day = 1)
            if BOM.month == 12:
                EOM = BOM.replace(year = BOM.year + 1, month = 1, day = 1) - \
                        dt.timedelta(microseconds = 1)
            else:
                EOM = BOM.replace(month = BOM.month + 1, day = 1) - \
                    dt.timedelta(microseconds = 1)
            #print('byMonth', record['date'], BOM, EOM)
            dailyRunStats = runTimes(c, table, BOM, EOM, record['fanRun'], record['auxRun'])
            lineRunTm = fmtRunTmLine(dailyRunStats)
        else:
            lineTemps = fmtTempsLine(name, record)
            ###print('else: start, end', start, end)
            lineRunTm = fmtRunTmLine(runTimes(c, table, start, end,
                                              record['fanRun'], record['auxRun']))
        print(lineTemps + lineRunTm)
        
def makeReport(c, thermostat, table):
    first, last = getYears(c, table)
    print('---------------------------', thermostat, '----------------------------')
    printHeader()
    makeSection(c, thermostat, table, 'Today')
    makeSection(c, thermostat, table, 'Prev7days', byDay = True)
    printHeader()
    makeSection(c, thermostat, table, 'Prev7daysLastYear', byDay = True)
    printHeader()
    for period in ['This Week', 'Last Week', 'This Month', 'Last Month']:
        makeSection(c, thermostat, table, period)
    for period in ['This Month', 'Last Month']:
        printHeader()
        for year in range(last.year, first.year - 1, -1):
            makeSection(c, thermostat, table, period, year = year)
    printHeader()
    makeSection(c, thermostat, table, 'YearByMonth', byMonth = True)
    makeSection(c, thermostat, table, 'LastYear')
    printHeader()
    for year in range(last.year, first.year - 1, -1):
        makeSection(c, thermostat, table, 'Year', year = year)
    print('')
    makeSection(c, thermostat, table,  'All')

    #printHeader()
    #makeSection(c, thermostat,  'All', byDay = True)
    
def main():
    EcobeeDB    = home + '/tools/Ecobee/Thermostats.sql'
    sqlite3.register_adapter(dt.datetime, adapt_datetime)
    sqlite3.register_converter("DATETIME", convert_datetime)
    db = sqlite3.connect(EcobeeDB, detect_types=sqlite3.PARSE_DECLTYPES)
    #db.set_trace_callback(print)
    db.row_factory = sqlite3.Row
    c = db.cursor()
        
    for thermostat in ['LivingRoom', 'Loft']:
        table = thermostat + 'X'
        makeReport(c, thermostat, table)

    print(insaneUsage)

if __name__ == '__main__':
  main()
