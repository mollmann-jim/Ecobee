#!/usr/bin/env python3
import datetime as dt
import sqlite3
from dateutil.tz import tz
from sys import path
path.append('/home/jim/tools/')
from shared import getTimeInterval

#DBname = '/home/jim/tools/Honeywell/MBthermostat3.sql'
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
    if row['minT']:
        period =  '{:>10s}'.format(tag)
        minT   = ' {:>5d}'.format(row['minT'])   if row['minT'] is not None else noData
        maxT   = ' {:>5d}'.format(row['maxT'])   if row['maxT'] is not None else noData
        avgT   = ' {:>5.1f}'.format(row['avgT']) if row['avgT'] is not None else noData
        minC   = ' {:>-5d}'.format(row['minC'])  if row['minC'] is not None else noData
        maxC   = ' {:>5d}'.format(row['maxC'])   if row['maxC'] is not None else noData
        avgC   = ' {:>5.1f}'.format(row['avgC']) if row['avgC'] is not None else noData
        minH   = ' {:>5d}'.format(row['minH'])   if row['minH'] is not None else noData
        maxH   = ' {:>5d}'.format(row['maxH'])   if row['maxH'] is not None else noData
        avgH   = ' {:>5.1f}'.format(row['avgH']) if row['avgH'] is not None else noData
        line = period + minT + maxT + avgT + minC + maxC + avgC + minH + maxH + avgH
    return line

def fmtRunTmLine(x):
    
    line = ''
    if x['elapsed'] > 0:
        heatPct = '{:>6.1f}'.format(100.0 * x['heat']  / x['elapsed'])
        coolPct = '{:>6.1f}'.format(100.0 * x['cool']  / x['elapsed'])
        fanPct  = '{:>6.1f}'.format(100.0 * x['fanOn'] / x['elapsed'])
        line = heatPct + coolPct + fanPct
    return line

def printHeader():
    #      2020/07/02 ttttt TTTTT aaaaa ccccc CCCCC aaaaa hhhhh HHHHH aaaaahhhhhhccccccffffff
    print('')
    print('                               Min   Max   Avg   Min   Max   Avg  Heat  Cool   Fan')
    print('             Min   Max   Avg  Cool  Cool  Cool  Heat  Heat  Heat   Run   Run   Run')
    print('            Temp  Temp  Temp   Set   Set   Set   Set   Set   Set     %     %     %')

def checkSanity(runStats, date, where):
    global insaneUsage
    for which in ['heat', 'cool', 'fanOn']:
        runPct = 100.0 * runStats[which] / runStats['elapsed']
        if runPct > saneUsageMax:
            fmt = '\n{:>10s} - {:>10s} {:>4s} utilization of {:>5.1f}% exceeds the {:>5.1f}%' \
                ' limit. Runtime = {:>8s}'
            runTime = str(dt.timedelta(seconds = runStats[which]))
            insaneUsage += fmt.format(date, where, which, runPct, saneUsageMax, runTime)
            return True
    return False
                                               
def runTimes(c, table, start, end):
    select = 'SELECT statusTime, fanOn, outputStatus FROM ' + table +\
        ' WHERE statusTime >= ? AND statusTime <= ? ;'
    c.execute(select, (start, end))
    result = c.fetchall()
    fanTime = heatTime = coolTime = 0
    first = last = previous = None
    for r in result:
        statTime = dt.datetime.strptime((r['statusTime']), '%Y-%m-%d %H:%M:%S')
        # may not have data for the entire time range
        # start, end if they are within 10 minutes. Otherwise first and last times.
        if first is None:
            if (statTime - start).total_seconds() < 600:
                first = start
                previous = start
            else:
                first = statTime
                previous = statTime + dt.timedelta(minutes =5)
        delta = (statTime - previous).total_seconds()
        # account for missing data by assuming 5 minutes
        if delta > 900: delta = 300
        if r['outputStatus'] == 'cool on':
            coolTime += delta
        elif r['outputStatus'] == 'heat on':
            heatTime += delta
        elif r['fanOn'] == 1:
            fanTime += delta
        elif r['outputStatus'] == 'off' and (r['fanOn'] == 0 or r['fanOn'] is None):
            # no fan/heat/cool - just idle
            pass
        elif r['outputStatus'] is None:
            # BayWeb data
            pass
        else:
            print('Unexpected: outputStatus:', r['outputStatus'], '\tfanOn:',  r['fanOn'])
        previous = statTime
    # in case no data (Monday)
    if previous:
        if (end - previous).total_seconds() < 600:
            last = end
        else:
            last = previous
        #print(start, end, first, last, (last - first).total_seconds())
        elapsed = (last - first).total_seconds()
    else:
        elapsed = 0
    return {'elapsed' : elapsed, 'heat' : heatTime, 'cool' : coolTime, 'fanOn': fanTime}

def getYears(c, thermostat):
    select_min_yr = 'SELECT min(statusTime) AS min FROM ' + thermostat + ';'
    c.execute(select_min_yr)
    min = c.fetchone()
    first = dt.datetime.strptime(min['min'], '%Y-%m-%d %H:%M:%S')
    select_max_yr = 'SELECT max(statusTime) AS max FROM ' + thermostat + ';'
    c.execute(select_max_yr)
    max = c.fetchone()
    last = dt.datetime.strptime(max['max'], '%Y-%m-%d %H:%M:%S')
    return first, last

def makeSection(c, thermostat, title, byDay = False, byMonth = False, year = None):
    start, end, name = getTimeInterval.getPeriod(title, year = year)
    selectFields =  'SELECT ' \
        'date(statusTime)  AS date, '\
        'max(temp)         AS maxT, '\
        'min(temp)         AS minT, '\
        'avg(temp)         AS avgT, '\
        'max(coolSetPoint) AS maxC, '\
        'min(coolSetPoint) AS minC, '\
        'avg(coolSetPoint) AS avgC, '\
        'max(heatSetPoint) AS maxH, '\
        'min(heatSetPoint) AS minH, '\
        'avg(heatSetPoint) AS avgH  '\
        ' FROM ' + thermostat +\
        ' WHERE statusTime >= ? AND statusTime <= ? '
    select = selectFields + ' ;'
    # sqlite date(timestamp) returns the UTC date
    selectByDay   = selectFields + ' GROUP BY substr(statusTime,1,10) ORDER BY statusTime DESC;'
    selectByMonth = selectFields + ' GROUP BY substr(statusTime,1, 7) ORDER BY statusTime DESC;'
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
            dailyRunStats = runTimes(c, thermostat, BOD, EOD)
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
            dailyRunStats = runTimes(c, thermostat, BOM, EOM)
            lineRunTm = fmtRunTmLine(dailyRunStats)
        else:
            lineTemps = fmtTempsLine(name, record)
            lineRunTm = fmtRunTmLine(runTimes(c, thermostat, start, end))
        print(lineTemps + lineRunTm)
        
def makeReport(c, thermostat):
    first, last = getYears(c, thermostat)
    print('---------------------------', thermostat, '----------------------------')
    printHeader()
    makeSection(c, thermostat, 'Today')
    makeSection(c, thermostat, 'Prev7days', byDay = True)
    printHeader()
    for period in ['This Week', 'Last Week', 'This Month', 'Last Month']:
        makeSection(c, thermostat,  period)
    for period in ['This Month', 'Last Month']:
        printHeader()
        for year in range(last.year, first.year - 1, -1):
            makeSection(c, thermostat, period, year = year)
    printHeader()
    makeSection(c, thermostat, 'YearByMonth', byMonth = True)
    makeSection(c, thermostat, 'LastYear')
    printHeader()
    for year in range(last.year, first.year - 1, -1):
        makeSection(c, thermostat, 'Year', year = year)
    print('')
    makeSection(c, thermostat,  'All')

    #printHeader()
    #makeSection(c, thermostat,  'All', byDay = True)
    
def main():
    #HoneywellDB = '/home/jim/tools/Honeywell/MBthermostat3.sql'
    #BayWebDB    = '/home/jim/tools/Honeywell/MBthermo.sql'
    #EcobeeDB    = '/home/jim/tools/Ecobee/MBthermostat.sql'
    EcobeeDB    = '/home/jim/tools/Ecobee/Thermostats.sql'
    WorkingDB   = '/home/jim/tools/Ecobee/Working.sql'
    WorkingDB   = ':memory:'
    Create = 'CREATE TABLE IF NOT EXISTS ZZZZZZZZ (\n' +\
        ' id             INTEGER PRIMARY KEY,      \n' +\
        ' statusTime     INTEGER,                  \n' +\
        ' temp           INTEGER,                  \n' +\
        ' coolSetPoint   INTEGER DEFAULT NULL,     \n' +\
        ' heatSetPoint   INTEGER DEFAULT NULL,     \n' +\
        ' fanOn          INTEGER,                  \n' +\
        ' outputStatus   TEXT                      \n' +\
        ' )'
    eCreate = 'CREATE TABLE IF NOT EXISTS ZZZZZZZZ (\n' +\
        ' id             INTEGER PRIMARY KEY,       \n' +\
        ' statusTime     INTEGER,                   \n' +\
        ' temp           INTEGER,                   \n' +\
        ' coolSetPoint   INTEGER DEFAULT NULL,      \n' +\
        ' heatSetPoint   INTEGER DEFAULT NULL,      \n' +\
        ' fanOn          INTEGER,                   \n' +\
        ' outputStatus   TEXT,                      \n' +\
        ' coolStatus     TEXT,                      \n' +\
        ' heatStatus     TEXT                       \n' +\
        ' )'
    eInsert = 'INSERT INTO ZZZZZZZZ         \n' +\
        '   ( statusTime,                   \n' +\
        '     temp,                         \n' +\
        '     coolSetPoint,                 \n' +\
        '     heatSetpoint,                 \n' +\
        '     outputStatus,                 \n' +\
        '     coolStatus,                   \n' +\
        '     heatStatus,                   \n' +\
        '     fanOn)                        \n' +\
        '  SELECT SUBSTR(statusTime,1,19) AS statusTime,   \n' +\
        '         ROUND(temp)             AS temp,         \n' +\
        '         ROUND(coolSetPoint)     AS coolSetPoint, \n' +\
        '         ROUND(heatSetpoint)     AS heatSetpoint, \n' +\
        '         NULL                    AS outputStatus, \n' +\
        '         coolStatus,                              \n' +\
        '         heatStatus,                              \n' +\
        '         fanOn                                    \n' +\
        '    FROM Edb.YYYYYYYY                             \n' +\
        '    ORDER BY statusTime                           \n'

    Insert = 'INSERT INTO ZZZZZZZZ          \n' +\
        '   ( statusTime,                   \n' +\
        '     temp,                         \n' +\
        '     coolSetPoint,                 \n' +\
        '     heatSetpoint,                 \n' +\
        '     outputStatus,                 \n' +\
        '     fanOn)                        \n' +\
        '  SELECT                           \n' +\
        '     statusTime,                   \n' +\
        '     temp,                         \n' +\
        '     coolSetPoint,                 \n' +\
        '     heatSetpoint,                 \n' +\
        '     outputStatus,                 \n' +\
        '     fanOn                         \n' +\
        '    FROM eYYYYYYYY                 \n' +\
        ';'
    Index    = 'CREATE INDEX IF NOT EXISTS ZZZZZZZZindex ON YYYYYYYY (statusTime)'
    UpdateC  = 'UPDATE ZZZZZZZZ SET coolSetPoint = NULL WHERE coolSetPoint == "null";'
    UpdateH  = 'UPDATE ZZZZZZZZ SET heatSetPoint = NULL WHERE heatSetPoint == "null";'
    UpdateT  = 'UPDATE ZZZZZZZZ SET temp         = NULL WHERE temp         == "null";'
    UpdateEc = 'UPDATE ZZZZZZZZ SET outputStatus = "cool on" WHERE coolStatus IS NOT NULL;'
    UpdateEh = 'UPDATE ZZZZZZZZ SET outputStatus = "heat on" WHERE heatStatus IS NOT NULL;'
    db = sqlite3.connect(WorkingDB)
    db.row_factory = sqlite3.Row
    c = db.cursor()
    #c.execute('ATTACH DATABASE "' + HoneywellDB + '" AS Hdb')
    #c.execute('ATTACH DATABASE "' + BayWebDB    + '" AS Bdb')
    c.execute('ATTACH DATABASE "' + EcobeeDB    + '" AS Edb')
    
    for thermostat in ['LivingRoom', 'Loft']:
        table = 'main.' + thermostat
        c.execute('DROP TABLE IF EXISTS ' + table)
        create = Create.replace('ZZZZZZZZ', table)
        #print(create)
        c.execute(create)
        
        index = Index.replace('ZZZZZZZZ', table)
        index = index.replace('YYYYYYYY', thermostat)
        #print(index)
        c.execute(index)
        
        # recode Ecobee coolStatus & heatStatus to outputStatus
        etable = 'main.e' + thermostat
        c.execute('DROP TABLE IF EXISTS ' + etable)
        ecreate = eCreate.replace('ZZZZZZZZ', etable)
        #print(ecreate)
        c.execute(ecreate)
        einsert = eInsert.replace('ZZZZZZZZ', etable)
        einsert = einsert.replace('YYYYYYYY', thermostat)
        #print(einsert)
        c.execute(einsert)
        db.commit()
        updateEc = UpdateEc.replace('ZZZZZZZZ', etable)
        #print(updateEc)
        c.execute(updateEc)
        db.commit()
        updateEh = UpdateEh.replace('ZZZZZZZZ', etable)
        #print(updateEh)
        c.execute(updateEh)
        db.commit()
        
        insert = Insert.replace('ZZZZZZZZ', table)
        insert = insert.replace('YYYYYYYY', thermostat)
        #print(insert)
        c.execute(insert)
        db.commit()
        update = UpdateC.replace('ZZZZZZZZ', table)
        c.execute(update)
        update = UpdateH.replace('ZZZZZZZZ', table)
        c.execute(update)
        update = UpdateT.replace('ZZZZZZZZ', table)
        c.execute(update)
        db.commit()
        #db.set_trace_callback(print)
        makeReport(c, thermostat)

    print(insaneUsage)

if __name__ == '__main__':
  main()
