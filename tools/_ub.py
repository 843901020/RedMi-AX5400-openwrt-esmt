#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Send a command to the U-Boot prompt and capture the reply.

usage: python _ub.py "printenv" ["help" ...]
       python _ub.py --raw "some long command"
"""
import sys
import time

import serial

import os

PORT = os.environ.get('UBPORT', 'COM6')
BAUD = 115200
PROMPT = b'IPQ5018#'


def clean(d):
    out = []
    for b in d:
        if 32 <= b < 127:
            out.append(chr(b))
        elif b == 0x0a:
            out.append('\n')
    return ''.join(out)


def run_cmd(ser, cmd, timeout=None, settle=0.6):
    if timeout is None:
        timeout = float(os.environ.get('UB_TIMEOUT', '25'))
    ser.reset_input_buffer()
    ser.write((cmd + '\r').encode())
    ser.flush()
    buf = b''
    t0 = time.time()
    got_prompt = False
    last_data = time.time()
    while time.time() - t0 < timeout:
        d = ser.read(4096)
        if d:
            buf += d
            last_data = time.time()
            if buf.rstrip().endswith(PROMPT):
                got_prompt = True
                break
        else:
            if got_prompt:
                break
            # no prompt yet, but if idle for a while after data, assume done
            if buf and time.time() - last_data > settle and buf.count(b'\n') > 0:
                if buf.rstrip().endswith(PROMPT):
                    break
    return buf


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    ser = serial.Serial(PORT, BAUD, bytesize=8, parity='N', stopbits=1, timeout=0.05)
    ser.reset_input_buffer()
    ser.write(b'\r')
    ser.flush()
    time.sleep(0.6)
    ser.reset_input_buffer()
    for c in args:
        print('\n' + '=' * 70)
        print('>>> %s' % c)
        print('=' * 70)
        out = run_cmd(ser, c)
        txt = clean(out)
        # drop the echoed command line
        lines = txt.split('\n')
        if lines and c[:20] in lines[0]:
            lines = lines[1:]
        print('\n'.join(l.rstrip() for l in lines))
    ser.close()


if __name__ == '__main__':
    main()
