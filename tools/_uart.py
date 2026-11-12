#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UART capture / interactive helper for the Redmi AX5400 (RA74) rescue.

usage:
  python _uart.py cap  <port> <baud> <seconds> [outfile]
  python _uart.py send <port> <baud> "<text>"      # sends text, then listens 5s
  python _uart.py menu <port> <baud>               # interactive passthrough
"""
import sys
import time

import serial


def hexdump_preview(d, n=64):
    s = d[:n]
    return ' '.join('%02x' % b for b in s) + (' ...' if len(d) > n else '')


def ascii_preview(d, n=200):
    out = []
    for b in d[:n]:
        if 32 <= b < 127:
            out.append(chr(b))
        elif b == 0x0a:
            out.append('\\n')
        elif b == 0x0d:
            out.append('\\r')
        else:
            out.append('.')
    return ''.join(out)


def cmd_cap(port, baud, dur, outfile):
    ser = serial.Serial(port, baud, bytesize=8, parity='N', stopbits=1, timeout=0.05)
    ser.reset_input_buffer()
    t0 = time.time()
    total = 0
    f = open(outfile, 'wb')
    try:
        while time.time() - t0 < dur:
            d = ser.read(4096)
            if not d:
                continue
            f.write(d)
            f.flush()
            total += len(d)
            print('[%7.3fs] +%-5d %s' % (time.time() - t0, len(d), ascii_preview(d)))
    finally:
        f.close()
        ser.close()
    print('\n--- captured %d bytes in %.1fs -> %s ---' % (total, dur, outfile))
    if total:
        raw = open(outfile, 'rb').read()
        print('--- full ascii dump ---')
        print(ascii_preview(raw, 4000))


def cmd_send(port, baud, text, listen=5.0):
    ser = serial.Serial(port, baud, bytesize=8, parity='N', stopbits=1, timeout=0.05)
    ser.reset_input_buffer()
    time.sleep(0.2)
    payload = text.encode().decode('unicode_escape').encode('latin1')
    ser.write(payload)
    ser.flush()
    print('sent %r' % payload)
    t0 = time.time()
    while time.time() - t0 < listen:
        d = ser.read(4096)
        if d:
            print('[%6.3fs] %s' % (time.time() - t0, ascii_preview(d)))
    ser.close()


def cmd_menu(port, baud):
    ser = serial.Serial(port, baud, bytesize=8, parity='N', stopbits=1, timeout=0.05)
    ser.reset_input_buffer()
    print('interactive: type a line then Enter. Ctrl-C to quit. (local echo off)')
    try:
        while True:
            d = ser.read(4096)
            if d:
                sys.stdout.write(ascii_preview(d, 4096).replace('\\n', '\n').replace('\\r', ''))
                sys.stdout.flush()
            if sys.stdin in __import__('select').select([sys.stdin], [], [], 0)[0]:
                line = sys.stdin.readline()
                if not line:
                    break
                ser.write(line.encode())
                ser.flush()
    except KeyboardInterrupt:
        pass
    finally:
        ser.close()


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'cap'
    if mode == 'cap':
        cmd_cap(sys.argv[2] if len(sys.argv) > 2 else 'COM5',
                int(sys.argv[3]) if len(sys.argv) > 3 else 115200,
                float(sys.argv[4]) if len(sys.argv) > 4 else 30,
                sys.argv[5] if len(sys.argv) > 5 else 'uart_capture2.log')
    elif mode == 'send':
        cmd_send(sys.argv[2], int(sys.argv[3]), sys.argv[4],
                 float(sys.argv[5]) if len(sys.argv) > 5 else 5.0)
    elif mode == 'menu':
        cmd_menu(sys.argv[2], int(sys.argv[3]))
    else:
        print(__doc__)
