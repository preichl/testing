#!/usr/bin/python3

from socket import socket
from threading import Thread
from sys import exit
from datetime import datetime
from urllib.parse import urlparse
from re import match
import argparse

parser = argparse.ArgumentParser(
    description='Send N requests on URL from X clients.')

parser.add_argument('URL', metavar='url', type=str, nargs='?',
                    help='URL to use for request')
parser.add_argument('-N', metavar='n', type=int, default=10,
                    help='Number of requests')
parser.add_argument('-X', metavar='n', type=int, default=1,
                    help='Number of clients')
parser.add_argument('--timeout', metavar='microseconds', type=int, default=-1,
                    help='Number of microseconds for which sesssion cookie is valid')
parser.add_argument('--print-response',
                    help='Print server response', action='store_true')
parser.add_argument('--print-request',
                    help='Print server response', action='store_true')
parser.add_argument('--print-session-cookie-expired',
                    help='Print server response', action='store_true')


def handler(opts):
    url = opts.get('url', None)
    if not url:
        print('Missing url')
        return

    # invalid url - let's assume it is http://
    if not match('(?:http|ftp|https)://', url):
        url = 'http://' + url

    o = urlparse(url)

    sc = None
    sc_changed = None
    for i in range(opts.get('req_num', 1)):
        # Session cookie expiration
        if sc and opts.get('sc_timeout', -1) != -1 and\
           (datetime.now() - sc_changed).microseconds > opts.get('sc_timeout', -1):
            sc = None
            if opts.get('print-session-cookie-expired', False):
                print('Session cookie expired')

        s = send_req(server=o.hostname,
                     port=o.port,
                     path=o.path,
                     sc=sc,
                     print_request=opts.get('print-request', False))
        sc_new = get_resp(s, opts.get('print-response', False))
        if sc_new and sc_new != sc:
            sc_changed = datetime.now()
            sc = sc_new


def get_resp(s, print_response):
    resp = s.recv(4096).decode()
    if print_response:
        print(resp)
    headers = resp[:resp.find('\r\n\r\n')]
    for line in headers.split('\r\n'):
        if line.find(':') != -1:
            tmp = line.split(':')
            name, value = tmp[0], tmp[1]
            if name.lower() == 'set-cookie':
                if value.lower().find('expires=') == -1:
                    return value
    return None


def send_req(server, port, path, sc, print_request):
    addr = str(server), port
    req = "GET {0} HTTP/1.1\r\nHost: {1}\r\n".format(path, server)

    if sc:
        req = req + 'Cookie: {0}\r\n'.format(sc)

    req = req + '\r\n'

    if print_request:
        print(req)   

    s = socket()
    r = s.connect(addr)
    req_len = s.send(req.encode())
    return s


def perform_requests(opts):

    threads = []
    for i in range(opts.get('cli_num', 1)):
        t = Thread(target=handler, args=(opts,))
        threads.append(t)

    for t in threads:
        t.start()

    for t in threads:
        t.join()


if __name__ == "__main__":

    args = parser.parse_args()

    if not args.URL:
        parser.print_help()
        exit(1)

    opts = {'cli_num': args.X,
            'req_num': args.N,
            'url': args.URL,
            'sc_timeout': args.timeout,
            'print-request': args.print_request,
            'print-response': args.print_response,
            'print-session-cookie-expired': args.print_session_cookie_expired}
    
    perform_requests(opts)

        
