#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Send `reset` then capture the boot log for N seconds.

usage: python _boot.py [seconds] [port] [outfile]
"""
import sys
import time

import serial

DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 90.0
PORT = sys.argv[2] if len(sys.argv) > 2 else 'COM6'
OUT = sys.argv[3] if len(sys.argv) > 3 else 'boot_after.log'

ser = serial.Serial(PORT, 115200, bytesize=8, parity='N', stopbits=1, timeout=0.05)
ser.reset_input_buffer()
ser.write(b'reset\r')
ser.flush()
print('已发送 reset，开始记录启动日志 %.0f 秒 ...\n' % DUR, flush=True)

f = open(OUT, 'wb')
t0 = time.time()
buf = b''
while time.time() - t0 < DUR:
    d = ser.read(8192)
    if not d:
        continue
    f.write(d)
    f.flush()
    buf += d
    while b'\n' in buf:
        line, buf = buf.split(b'\n', 1)
        s = line.decode('latin1').replace('\r', '').strip()
        if not s or 'ecc failure' in s:
            continue
        print('[%6.2fs] %s' % (time.time() - t0, s), flush=True)
f.close()
ser.close()
print('\n--- 记录结束 -> %s ---' % OUT)
