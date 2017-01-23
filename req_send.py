#!/usr/bin/python

from socket import socket
from threading import Thread
from sys import exit
from datetime import datetime
import argparse

parser = argparse.ArgumentParser(description='Send N requests on URL from X clients.')

parser.add_argument('URL', metavar='url', type=str, nargs='?',
                    help='URL to use for request')
parser.add_argument('-N', metavar='n', type=int, default=10,
                    help='Number of requests')
parser.add_argument('-X', metavar='n', type=int, default=1,
                    help='Number of clients')
parser.add_argument('--timeout', metavar='microseconds', type=int, default=1,
                    help='Number of microseconds for which sesssion cookie is valid')

args = parser.parse_args()

if not args.URL:
    parser.print_help()
    exit(1)

url = args.URL
req_num = args.N
cli_num = args.X
site = '/'
sc_timeout = args.timeout

def handler(req_num, url, site):
    sc = None
    sc_changed = None
    for i in range(req_num):
        # Session cookie expiration
        if sc and \
           (datetime.now() - sc_changed).microseconds > sc_timeout:
            sc = None
            print('Session cookie expired')

        s = send_req(url, site, sc)
        sc_new = get_resp(s)
        if sc_new and sc_new != sc:
            sc_changed = datetime.now()
            sc = sc_new


def get_resp(s):
    resp = s.recv(4096)
    #print(resp)
    headers = resp[:resp.find('\r\n\r\n')]
    for line in headers.split('\r\n'):
        if line.find(':') != -1:
            tmp = line.split(':')
            name, value = tmp[0], tmp[1]
            if name.lower() == 'set-cookie':
                if value.lower().find('expires=') == -1:
                    return value
    return None


def send_req(url, site, sc, port=80):
    addr = url, port
    req = "GET {0} HTTP/1.1\r\nHost: example.com\r\n".format(site)

    if sc:
        req = req + 'Cookie: {0}\r\n'.format(sc)

    req = req + '\r\n'

    #print(req)

    s = socket()
    r = s.connect(addr)
    req_len = s.send(req)
    return s


threads = []
for i in range(cli_num):
    t = Thread(target=handler, args=(req_num, url, site))
    threads.append(t)

for t in threads:
    t.start()

for t in threads:
    t.join()
