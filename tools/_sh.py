#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run shell commands on the router's Linux console over the serial port.

usage: python _sh.py "cmd1" "cmd2" ...
env: SHPORT (default COM6), SHBAUD (115200), SHPROMPT (default 'root@OpenWrt')
"""
import os
import sys
import time

import serial

PORT = os.environ.get('SHPORT', 'COM6')
BAUD = int(os.environ.get('SHBAUD', '115200'))
PROMPT = os.environ.get('SHPROMPT', 'root@OpenWrt')


def run_cmd(ser, cmd, timeout=None):
    if timeout is None:
        timeout = float(os.environ.get('SH_TIMEOUT', '30'))
    ser.reset_input_buffer()
    ser.write((cmd + '\r').encode())
    ser.flush()
    buf = b''
    t0 = time.time()
    last = time.time()
    while time.time() - t0 < timeout:
        d = ser.read(4096)
        if d:
            buf += d
            last = time.time()
        else:
            tail = buf.decode('latin1')
            if PROMPT in tail and tail.rstrip().endswith('#'):
                if time.time() - last > 0.25:
                    break
    return buf.decode('latin1').replace('\r', '')


def main():
    cmds = sys.argv[1:]
    ser = serial.Serial(PORT, BAUD, bytesize=8, parity='N', stopbits=1, timeout=0.05)
    ser.reset_input_buffer()
    ser.write(b'\r')
    ser.flush()
    time.sleep(0.6)
    ser.reset_input_buffer()
    for cmd in cmds:
        print('=' * 68)
        print('>>> %s' % cmd)
        print('=' * 68)
        out = run_cmd(ser, cmd)
        lines = out.split('\n')
        # 去掉命令回显和末尾提示符
        if lines and cmd[:15] in lines[0]:
            lines = lines[1:]
        txt = '\n'.join(l.rstrip() for l in lines).rstrip()
        if txt.endswith('#'):
            txt = txt[:txt.rfind(PROMPT)] if PROMPT in txt else txt
        print(txt.rstrip())
        print()
    ser.close()


if __name__ == '__main__':
    main()
