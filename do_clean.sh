#!/usr/bin/bash

rm -rf apache-tomcat-7.0.73 apr-1.5.2 apr-util-1.5.4 httpd-2.4.25
rm -rf /tmp/usr
cd mod_cluster && git reset --hard HEAD
