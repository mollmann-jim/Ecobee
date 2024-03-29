#!/bin/bash
set -x
logDir="/home/jim/tools/Ecobee/logs"
outLogStem="$logDir/Ecobee."
outLogStemNC="$logDir/Ecobee.NC."
outLogStemSC="$logDir/Ecobee.SC."
logLogStem="$logDir/ecobee.log."
timestamp=$(/bin/date +%F-%T | /bin/tr : .);
outLog=$outLogStem$timestamp
outLogNC=$outLogStemNC$timestamp
outLogSC=$outLogStemSC$timestamp
logLog=$logLogStem$timestamp
touch $outLog $outLogNC $outLogSC
touch $logLog
/bin/rm $logDir/../ecobee.log
/bin/ln $logLog $logDir/../ecobee.log
# keep only the newest
for prefix in $outLogStem $logLogStemNC $logLogStemSC; do
    REMOVE=$(ls -t $prefix* | sed 1,20d)
    if [ -n "$REMOVE" ]; then
	/bin/rm $REMOVE
    fi
done
#/home/jim/tools/SolarEdge/collectLayout.py > $log 2>&1
cd /home/jim/tools/Ecobee/
while true; do
    /usr/bin/date >> $outLogNC
    /usr/bin/date >> $outLogSC
    echo '============================================================' >> $outLog
    /home/jim/tools/Ecobee/EcoBee.py >> $outLog 2>&1 7>>$outLogNC 8>>$outLogSC
    sleep 5
done
#
# unreacable?
#
cat $outLog
