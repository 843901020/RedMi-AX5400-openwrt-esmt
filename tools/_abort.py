#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Try to abort the running U-Boot command with Ctrl-C and land on the prompt.

U-Boot's ctrlc() aborts the currently executing command; after the abort the
main loop prints its prompt. If serial TX is wired, this should break out of
the `cmd=dhcp` retry loop that the recovery flow is stuck in.

usage: python _abort.py [port] [baud] [seconds]
"""
import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else 'COM5'
BAUD = int(sys.argv[2]) if len(sys.argv) > 2 else 115200
DUR = float(sys.argv[3]) if len(sys.argv) > 3 else 30.0
OUT = sys.argv[4] if len(sys.argv) > 4 else 'abort.log'

PROMPTS = ('=>', 'AX5400#', 'miwifi#', 'RA74#', 'IPQ#', '#')


def clean(d):
    out = []
    for b in d:
        if 32 <= b < 127:
            out.append(chr(b))
        elif b == 0x0a:
            out.append('\n')
    return ''.join(out)


ser = serial.Serial(PORT, BAUD, bytesize=8, parity='N', stopbits=1, timeout=0.05)
ser.reset_input_buffer()
f = open(OUT, 'wb')
t0 = time.time()
last = 0.0
buf = ''
prompt_hit = False

print('每 250ms 发送一次 Ctrl-C (0x03)，持续 %.0fs ...' % DUR, flush=True)
while time.time() - t0 < DUR:
    now = time.time()
    if now - last > 0.25:
        ser.write(b'\x03')
        ser.flush()
        last = now
    d = ser.read(8192)
    if not d:
        continue
    f.write(d)
    f.flush()
    buf += clean(d)
    while '\n' in buf:
        line, buf = buf.split('\n', 1)
        s = line.strip()
        if not s or 'ecc failure' in s:
            continue
        print('[%6.2fs] %s' % (now - t0, s), flush=True)
    for p in PROMPTS:
        if buf.rstrip().endswith(p) or ('\n' + p) in buf:
            prompt_hit = True
    if '=>' in buf:
        prompt_hit = True

f.close()
ser.close()
print('\n--- 结束 ---')
print('看到 U-Boot 提示符: %s' % ('是 ✔' if prompt_hit else '否 ✘'))
print('日志 -> %s' % OUT)
