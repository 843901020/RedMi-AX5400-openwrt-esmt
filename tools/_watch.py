#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Quiet long-running UART watcher: logs raw bytes, prints only interesting lines."""
import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else 'COM5'
BAUD = int(sys.argv[2]) if len(sys.argv) > 2 else 115200
DUR = float(sys.argv[3]) if len(sys.argv) > 3 else 120.0
OUT = sys.argv[4] if len(sys.argv) > 4 else 'watch.log'

ser = serial.Serial(PORT, BAUD, bytesize=8, parity='N', stopbits=1, timeout=0.05)
ser.reset_input_buffer()
f = open(OUT, 'wb')
t0 = time.time()
buf = b''
print('watching %s @ %d for %.0fs -> %s' % (PORT, BAUD, DUR, OUT), flush=True)

while time.time() - t0 < DUR:
    d = ser.read(8192)
    if not d:
        continue
    f.write(d)
    f.flush()
    buf += d
    # split on newline, only report complete lines without ecc noise
    while b'\n' in buf:
        line, buf = buf.split(b'\n', 1)
        s = line.decode('latin1').replace('\r', '').strip()
        if not s:
            continue
        if 'ecc failure' in s:
            continue
        print('[%6.2fs] %s' % (time.time() - t0, s), flush=True)

f.close()
ser.close()
print('--- watch finished, %d bytes -> %s ---' % (time.time() - t0 and 0 or 0, OUT), flush=True)
