#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hammer a key on the UART to break into the U-Boot prompt.

The device boot-loops, so we just keep spamming CR; sooner or later one lands
inside the 3s autoboot window and drops us to the `bootmiwifi` console.

usage: python _uboot_stop.py [port] [baud] [seconds]
"""
import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else 'COM5'
BAUD = int(sys.argv[2]) if len(sys.argv) > 2 else 115200
DUR = float(sys.argv[3]) if len(sys.argv) > 3 else 40.0
OUT = sys.argv[4] if len(sys.argv) > 4 else 'uboot_stop.log'


def vis(d, n=4096):
    out = []
    for b in d[:n]:
        if 32 <= b < 127:
            out.append(chr(b))
        elif b == 0x0a:
            out.append('\n')
        elif b == 0x0d:
            pass
        else:
            out.append('.')
    return ''.join(out)


ser = serial.Serial(PORT, BAUD, bytesize=8, parity='N', stopbits=1, timeout=0.02)
ser.reset_input_buffer()
f = open(OUT, 'wb')
t0 = time.time()
last_send = 0.0
hits = 0
print('spamming CR on %s @ %d for %.0fs ...' % (PORT, BAUD, DUR))

while time.time() - t0 < DUR:
    now = time.time()
    if now - last_send > 0.08:
        ser.write(b'\r')
        ser.flush()
        last_send = now
    d = ser.read(8192)
    if not d:
        continue
    f.write(d)
    f.flush()
    txt = vis(d)
    if 'ecc failure' in txt:
        # collapse the noise so the interesting lines stay readable
        print('[%6.2fs] <ecc-failure flood, %d bytes>' % (now - t0, len(d)))
        hits += 1
        continue
    if txt.strip():
        print('[%6.2fs] %s' % (now - t0, txt.rstrip()))

f.close()
ser.close()
print('\n--- done, log -> %s (ecc chunks: %d) ---' % (OUT, hits))
