#!/bin/bash
#set -x
logDir="/home/jim/tools/Ecobee/logs"
log=$logDir/report.$(/bin/date +%F-%T | /bin/tr : .);
#/home/jim/tools/Ecobee/reportNMBThermostat.py > $log 2>&1
/home/jim/tools/Ecobee/reportNCThermostat.py  > $log 2>&1
cat $log
# keep only the newest
REMOVE=$(ls -t $logDir/report* | sed 1,20d)
if [ -n "$REMOVE" ]; then
    /bin/rm $REMOVE
fi
grep -q 'High Usage' $log
if [[ $? -eq "0" ]]; then
    Alert="*** High Usage ***"
else
    Alert=""
fi

me=jim.mollmann@gmail.com
(echo -e "Subject: $Alert NC Thermostat Usage Report: $(date)\n"; cat $log) | sendmail $me

