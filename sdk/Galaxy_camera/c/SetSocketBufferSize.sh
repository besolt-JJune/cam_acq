#!/bin/sh
# ***************************************************************************************
#     set_socket_buffer_size.sh
# Set the MAX buffer size of Rx and Tx, Default to set 10M Byte, it can adjust the size through
# the parameter.For example:
# sudo ./set_socket_buffer_size.sh  15728640
# It set the Rx and Tx buffer size to 15M
# ***************************************************************************************

OS_NAME=`uname --`

if [ "$1" = "" ]; then
  SIZE=10485760	#10M
else
  SIZE=$1
fi

echo "Setting socket maximum buffer size to $SIZE"

USER_ID=`id -u`
# Check required priviledge
if [ "$USER_ID" != "0" ]; then
    echo "This script can only be run by root user or sudoer"
    exit 1
fi

if [ "$OS_NAME" = "Linux" ]; then
  PROC_ROOT=/proc/sys/net/core

  if [ ! -w $PROC_ROOT/wmem_max ]; then
    echo "Cannot write to $PROC_ROOT/wmem_max"
    exit 1
  fi

  if [ ! -w $PROC_ROOT/rmem_max ]; then
    echo "Cannot write to $PROC_ROOT/rmem_max"
    exit 1
  fi

  echo $SIZE > $PROC_ROOT/wmem_max
  echo $SIZE > $PROC_ROOT/rmem_max

  # If the system set the value of net.core.rmem_max and net.core.wmem_max in /etc/sysctl.conf, change value to "$SIZE"
  #	else, add "net.core.rmem_max = $SIZE" and "net.core.wmem_max = $SIZE" to /etc/sysctl.conf
  if grep --silent ^net.core.rmem_max /etc/sysctl.conf; then
    sed -i 's/^net.core.rmem_max.*/net.core.rmem_max = '$SIZE'/g' /etc/sysctl.conf
  else
    echo "" >> /etc/sysctl.conf
    echo "net.core.rmem_max = $SIZE" >> /etc/sysctl.conf
  fi
  
  if grep --silent ^net.core.wmem_max /etc/sysctl.conf; then
    sed -i 's/^net.core.wmem_max.*/net.core.wmem_max = '$SIZE'/g' /etc/sysctl.conf
  else
    echo "" >> /etc/sysctl.conf
    echo "net.core.wmem_max = $SIZE" >> /etc/sysctl.conf
  fi
  
  
  exit 0
fi

echo "Error: unknown platform: $OS_NAME"
exit 1

