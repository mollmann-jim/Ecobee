#!/bin/bash
#set -x
logDir="$HOME/tools/Ecobee/logs"
reportDir="$HOME/SynologyDrive/Reports.Daily/"
log=$logDir/report.$(/bin/date +%F-%T | /usr/bin/tr : .);
#$HOME/tools/Ecobee/reportNMBThermostat.py > $log 2>&1
$HOME/tools/Ecobee/reportNCThermostat.py  > $log 2>&1
cp -p $log $reportDir/NC.Thermostat.txt
cp -p $log $reportDir/All/NC.Thermostat.$(basename -- "$log").txt
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
#### (echo -e "Subject: $Alert NC Thermostat Usage Report: $(date)\n"; cat $log) | sendmail $me

