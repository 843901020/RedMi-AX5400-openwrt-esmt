#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Standalone TFTP server for pushing the NAND partition images into U-Boot RAM.

Serves every file in ROOT; ignores the requested name (logs it) so U-Boot can
ask for whatever it wants.

usage: python _tftp.py [root_dir]
"""
import os
import socket
import struct
import sys
import threading
import time

ROOT = sys.argv[1] if len(sys.argv) > 1 else \
    'xmir-patcher/xmir-patcher-main/backupsbak'
OP_RRQ, OP_WRQ, OP_DATA, OP_ACK, OP_ERROR, OP_OACK = 1, 2, 3, 4, 5, 6
LOCK = threading.Lock()


def log(m):
    with LOCK:
        print('[%s] %s' % (time.strftime('%H:%M:%S'), m), flush=True)
        with open('tftp_serve.log', 'a', encoding='utf-8') as f:
            f.write('[%s] %s\n' % (time.strftime('%H:%M:%S'), m))


def resolve(name):
    """Map a requested filename to a local file (exact match, else single .bin)."""
    p = os.path.join(ROOT, name)
    if os.path.isfile(p):
        return p
    base = os.path.basename(name)
    p = os.path.join(ROOT, base)
    if os.path.isfile(p):
        return p
    # fall back: unique file containing the requested stem
    stem = os.path.splitext(base)[0].lower()
    cands = [f for f in os.listdir(ROOT) if stem[:12] in f.lower()]
    if len(cands) == 1:
        return os.path.join(ROOT, cands[0])
    return None


def serve(client, payload):
    parts = payload.split(b'\x00')
    fname = parts[0].decode(errors='replace')
    opts = {}
    for i in range(2, len(parts) - 1, 2):
        k = parts[i].decode(errors='replace').lower()
        v = parts[i + 1].decode(errors='replace')
        if k:
            opts[k] = v

    path = resolve(fname)
    if not path:
        log('!! 请求的文件找不到: %r' % fname)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.sendto(struct.pack('!HH', OP_ERROR, 1) + b'not found\x00', client)
        s.close()
        return
    data = open(path, 'rb').read()
    total = len(data)
    blksize = 512
    if 'blksize' in opts:
        try:
            blksize = max(8, min(65464, int(opts['blksize'])))
        except ValueError:
            blksize = 512
    log('>>> %s:%d 请求 %r -> 发送 %s (%d 字节, blksize=%d)'
        % (client[0], client[1], fname, os.path.basename(path), total, blksize))

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(('', 0))
    s.settimeout(4.0)

    neg = [k for k in ('blksize', 'tsize', 'timeout') if k in opts]
    if neg:
        body = b''
        for k in neg:
            v = str(blksize) if k == 'blksize' else (str(total) if k == 'tsize' else opts[k])
            body += k.encode() + b'\x00' + v.encode() + b'\x00'
        s.sendto(struct.pack('!H', OP_OACK) + body, client)
        try:
            p, _ = s.recvfrom(1024)
            if struct.unpack('!H', p[:2])[0] != OP_ACK:
                log('   OACK 未确认，继续')
        except socket.timeout:
            log('   OACK 超时，继续')

    n = (total + blksize - 1) // blksize
    t0 = time.time()
    for bn in range(1, n + 1):
        chunk = data[(bn - 1) * blksize: bn * blksize]
        pkt = struct.pack('!HH', OP_DATA, bn & 0xFFFF) + chunk
        ok = False
        for _ in range(10):
            s.sendto(pkt, client)
            try:
                ack, _ = s.recvfrom(1024)
                if struct.unpack('!H', ack[:2])[0] == OP_ACK and \
                        struct.unpack('!H', ack[2:4])[0] == (bn & 0xFFFF):
                    ok = True
                    break
            except socket.timeout:
                continue
        if not ok:
            log('   !! 块 %d/%d 失败，放弃' % (bn, n))
            s.close()
            return
        if bn % 4000 == 0 or bn == n:
            log('   进度 %d/%d (%.1f%%)  %.0f KB/s'
                % (bn, n, bn * 100.0 / n, bn * blksize / 1024.0 / max(.01, time.time() - t0)))
    s.close()
    log('<<< 完成 %d 字节, %.1fs' % (total, time.time() - t0))


def main():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(('0.0.0.0', 69))
    except OSError as e:
        print('无法绑定 UDP 69: %s' % e)
        return 1
    s.settimeout(1.0)
    files = sorted(f for f in os.listdir(ROOT) if f.endswith('.bin'))
    print('TFTP 服务器已启动  根目录: %s' % os.path.abspath(ROOT))
    print('可提供的文件 (%d 个):' % len(files))
    for f in files:
        print('   %-28s %10d' % (f, os.path.getsize(os.path.join(ROOT, f))))
    print('等待请求 ... (Ctrl-C 结束)', flush=True)
    while True:
        try:
            pkt, addr = s.recvfrom(2048)
        except socket.timeout:
            continue
        except KeyboardInterrupt:
            break
        if len(pkt) >= 4 and struct.unpack('!H', pkt[:2])[0] == OP_RRQ:
            threading.Thread(target=serve, args=(addr, pkt[2:]), daemon=True).start()
    return 0


if __name__ == '__main__':
    sys.exit(main())
