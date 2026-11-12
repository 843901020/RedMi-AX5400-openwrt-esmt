#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tiny reverse proxy so the router can reach downloads.openwrt.org
through this PC (the PC has internet via USB tethering, the router doesn't).

GET /snapshots/...  ->  https://downloads.openwrt.org/snapshots/...

usage: python _apkproxy.py [port]
"""
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = 'https://downloads.openwrt.org'
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        sys.stderr.write('[%s] %s\n' % (self.address_string(), fmt % args))

    def do_GET(self):
        url = UPSTREAM + self.path
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'apk-proxy/1.0'})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
                ctype = r.headers.get('Content-Type', 'application/octet-stream')
            self.send_response(200)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            print('[proxy] 200 %s (%d 字节)' % (self.path, len(data)), flush=True)
        except urllib.error.HTTPError as e:
            print('[proxy] %d %s' % (e.code, self.path), flush=True)
            self.send_error(e.code)
        except Exception as e:
            print('[proxy] ERR %s -> %s' % (self.path, e), flush=True)
            self.send_error(502)


if __name__ == '__main__':
    print('反向代理已启动: http://0.0.0.0:%d  ->  %s' % (PORT, UPSTREAM), flush=True)
    ThreadingHTTPServer(('0.0.0.0', PORT), Handler).serve_forever()
