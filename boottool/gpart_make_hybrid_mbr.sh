#!/usr/bin/env bash

argcount=2
usage="exp_script_path boot_device"
test "$#" -eq "${argcount}" || { echo "$0 ${usage}" > /dev/stderr && exit 1 ; } #"-ge=>=" "-gt=>" "-le=<=" "-lt=<" "-ne=!="

exp_script=$(readlink -f "${1}")
shift

device="${1}"
test -b "${device}" || { echo "$0: ${device} not found or is not a block device. Exiting." > /dev/stderr ; exit 1 ; }
#mount | grep "${device}" && { echo "$0: ${device} is mounted. Exiting." ; exit 1 ; }

echo "$0: making hybrid MBR"
"${exp_script}" "${device}" || exit 1
echo "$0: making hybrid MBR exited 0, should be good to go."
