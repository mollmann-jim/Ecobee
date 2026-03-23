#!/bin/bash
#set -x
logDir="$HOME/tools/Ecobee/logs"
log=$logDir/report.$(/bin/date +%F-%T | /usr/bin/tr : .);
reportDir="$HOME/SynologyDrive/Reports.Daily/"
reportName="NC.Thermostat"
if [[ "$HOSTNAME" != "jim4" ]]; then
    newAge=77
    updated=$(find $HOME/SynologyDrive/Reports.Daily/ -name $reportName.txt -mmin -$newAge | wc -l)
    if [[ $(($updated + 0 ))  > 0 ]]; then
	#echo already run
	exit 0
    fi
fi
echo -e "------- $HOSTNAME --------- $(date) --------\n" > $log
$HOME/tools/Ecobee/reportNCThermostat.py  >> $log 2>&1
reportFile="$reportDir/$reportName.txt"
cat $log | sed '1s/^/<div><tt>\n/g' | sed '$sZ$Z\n</tt></div>Zg' > $reportFile
reportHistory="$reportDir/All/$reportName.$(basename -- "$log").txt"
cp $reportFile $reportHistory

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

