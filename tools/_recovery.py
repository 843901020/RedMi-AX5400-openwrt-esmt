#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Xiaomi U-Boot recovery feeder that works with the PC's EXISTING IP.

The router's recovery flow does:  ping serverip -> dhcp -> tftp get <fw>
We answer the DHCP DISCOVER ourselves, hand out an address in the same /16 as
the PC, and advertise ourselves as the TFTP server (siaddr + option 66) so
U-Boot's `serverip` ends up pointing at this machine - no NIC reconfiguration.

usage: python _recovery.py <firmware-file>
"""
import os
import socket
import struct
import sys
import threading
import time

FW = sys.argv[1] if len(sys.argv) > 1 else 'miwifi_ra74_firmware_7937d_1.0.63.bin'
SERVER_IP = os.environ.get('REC_SERVER', '169.254.4.25')
CLIENT_IP = os.environ.get('REC_CLIENT', '169.254.4.100')
NETMASK = os.environ.get('REC_MASK', '255.255.0.0')
BOOTFILE = os.path.basename(FW)

OP_RRQ, OP_DATA, OP_ACK, OP_ERROR, OP_OACK = 1, 3, 4, 5, 6
LOCK = threading.Lock()


def log(m):
    with LOCK:
        line = '[%s] %s' % (time.strftime('%H:%M:%S'), m)
        print(line, flush=True)
        with open('recovery.log', 'a', encoding='utf-8') as f:
            f.write(line + '\n')


def ip2b(s):
    return socket.inet_aton(s)


def parse_opts(data):
    opts, i = {}, 0
    while i < len(data):
        c = data[i]
        if c == 0:
            i += 1
            continue
        if c == 255 or i + 1 >= len(data):
            break
        ln = data[i + 1]
        opts[c] = data[i + 2:i + 2 + ln]
        i += 2 + ln
    return opts


def build_reply(req, mtype):
    xid = req[4:8]
    flags = req[10:12]
    chaddr = req[28:44]
    p = bytearray()
    p += bytes([2, 1, 6, 0]) + xid + b'\x00\x00' + flags
    p += b'\x00' * 4
    p += ip2b(CLIENT_IP)
    p += ip2b(SERVER_IP)
    p += b'\x00' * 4
    p += chaddr + b'\x00' * (16 - len(chaddr))
    p += b'\x00' * 64
    bf = BOOTFILE.encode()[:127]
    p += bf + b'\x00' * (128 - len(bf))
    p += b'\x63\x82\x53\x63'

    def opt(code, val):
        p.extend(bytes([code, len(val)]) + val)

    opt(53, bytes([mtype]))
    opt(54, ip2b(SERVER_IP))
    opt(51, struct.pack('!I', 3600))
    opt(1, ip2b(NETMASK))
    opt(3, ip2b(SERVER_IP))
    opt(6, ip2b(SERVER_IP))
    opt(66, SERVER_IP.encode())      # TFTP server name -> U-Boot sets serverip
    opt(67, BOOTFILE.encode())       # boot file name
    p += b'\xff'
    if len(p) < 300:
        p += b'\x00' * (300 - len(p))
    return bytes(p)


def dhcp_server():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        s.bind(('0.0.0.0', 67))
    except OSError as e:
        log('ERROR 绑定 UDP 67 失败 (%s) - 需要管理员权限' % e)
        return
    s.settimeout(1.0)
    log('DHCP 就绪: 服务器 %s, 分配 %s, bootfile=%s' % (SERVER_IP, CLIENT_IP, BOOTFILE))
    while True:
        try:
            pkt, addr = s.recvfrom(2048)
        except socket.timeout:
            continue
        except OSError:
            break
        if len(pkt) < 240 or pkt[0] != 1:
            continue
        o = parse_opts(pkt[240:])
        t = o.get(53, b'\x00')[0]
        mac = ':'.join('%02x' % b for b in pkt[28:34])
        if t == 1:
            log('DISCOVER from %s (%s) -> OFFER' % (addr[0], mac))
            s.sendto(build_reply(pkt, 2), ('255.255.255.255', 68))
        elif t == 3:
            log('REQUEST  from %s (%s) -> ACK' % (addr[0], mac))
            s.sendto(build_reply(pkt, 5), ('255.255.255.255', 68))


def tftp_serve(client, payload):
    parts = payload.split(b'\x00')
    fname = parts[0].decode(errors='replace')
    opts = {}
    for i in range(2, len(parts) - 1, 2):
        k = parts[i].decode(errors='replace').lower()
        v = parts[i + 1].decode(errors='replace')
        if k:
            opts[k] = v
    data = open(FW, 'rb').read()
    total = len(data)
    blk = 512
    if 'blksize' in opts:
        try:
            blk = max(8, min(65464, int(opts['blksize'])))
        except ValueError:
            blk = 512
    log('>>> %s:%d 请求 %r -> 发送 %s (%d 字节, blksize=%d)'
        % (client[0], client[1], fname, BOOTFILE, total, blk))

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(('', 0))
    s.settimeout(4.0)
    neg = [k for k in ('blksize', 'tsize', 'timeout') if k in opts]
    if neg:
        body = b''
        for k in neg:
            v = str(blk) if k == 'blksize' else (str(total) if k == 'tsize' else opts[k])
            body += k.encode() + b'\x00' + v.encode() + b'\x00'
        s.sendto(struct.pack('!H', OP_OACK) + body, client)
        try:
            p, _ = s.recvfrom(1024)
            if struct.unpack('!H', p[:2])[0] != OP_ACK:
                log('   OACK 未确认，继续')
        except socket.timeout:
            log('   OACK 超时，继续')

    n = (total + blk - 1) // blk
    t0 = time.time()
    for bn in range(1, n + 1):
        chunk = data[(bn - 1) * blk: bn * blk]
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
            log('   !! 块 %d/%d 失败' % (bn, n))
            s.close()
            return
        if bn % 4000 == 0 or bn == n:
            log('   进度 %d/%d (%.1f%%) %.0f KB/s'
                % (bn, n, bn * 100.0 / n, bn * blk / 1024.0 / max(.01, time.time() - t0)))
    s.close()
    log('<<< 固件发送完成 %d 字节, %.1fs' % (total, time.time() - t0))


def tftp_server():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(('0.0.0.0', 69))
    except OSError as e:
        log('ERROR 绑定 UDP 69 失败 (%s)' % e)
        return
    s.settimeout(1.0)
    log('TFTP 就绪, 提供 %s (%d 字节)' % (BOOTFILE, os.path.getsize(FW)))
    while True:
        try:
            pkt, addr = s.recvfrom(2048)
        except socket.timeout:
            continue
        except OSError:
            break
        if len(pkt) >= 4 and struct.unpack('!H', pkt[:2])[0] == OP_RRQ:
            threading.Thread(target=tftp_serve, args=(addr, pkt[2:]), daemon=True).start()


def main():
    if not os.path.exists(FW):
        print('找不到固件: %s' % FW)
        return 1
    print('=' * 62)
    print(' 小米 U-Boot 恢复喂送器（不改网卡 IP）')
    print('=' * 62)
    print(' 服务器 : %s' % SERVER_IP)
    print(' 分配   : %s / %s' % (CLIENT_IP, NETMASK))
    print(' 固件   : %s (%d 字节)' % (BOOTFILE, os.path.getsize(FW)))
    print('=' * 62)
    threading.Thread(target=dhcp_server, daemon=True).start()
    threading.Thread(target=tftp_server, daemon=True).start()
    time.sleep(0.5)
    print('\n现在请：拔电源 -> 按住 Reset -> 插电 -> 按住 12 秒 -> 松开')
    print('Ctrl-C 结束\n')
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print('\n已停止')
    return 0


if __name__ == '__main__':
    sys.exit(main())
