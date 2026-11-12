#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Patch nand-ecc-strength inside the kernel volume of an OpenWrt UBI image.

The AX5400 DTB hardcodes nand-ecc-strength = <8> (needs 128-byte OOB); units
with an ESMT F50D1G41LB have only 64 bytes of OOB and need <4>.

UBI kernel volumes are *dynamic* (vol_type=1), so data_size/data_crc are unused
and only the 64-byte VID header is CRC-protected.  Patching bytes inside the
data area therefore needs no UBI metadata fixup - only the FIT hash nodes.

usage: python _ubipatch.py <in.ubi> <out.ubi> [strength]
"""
import hashlib
import struct
import sys
import zlib

PEB = 131072
STRENGTH = int(sys.argv[3]) if len(sys.argv) > 3 else 4


def be32(b, o):
    return struct.unpack('>I', b[o:o + 4])[0]


def walk(b, off):
    f = struct.unpack('>10I', b[off:off + 40])
    if f[0] != 0xd00dfeed:
        raise ValueError('not an FDT at 0x%x' % off)
    p = off + f[2]
    end = p + f[9]
    path = []
    while p < end:
        tok = be32(b, p)
        p += 4
        if tok == 1:
            e = b.index(b'\x00', p)
            path.append(b[p:e].decode(errors='replace'))
            p = (e + 1 + 3) & ~3
        elif tok == 2:
            if path:
                path.pop()
        elif tok == 3:
            ln = be32(b, p)
            noff = be32(b, p + 4)
            p += 8
            vabs = p
            val = b[p:p + ln]
            p = (p + ln + 3) & ~3
            s = off + f[3] + noff
            e = b.index(b'\x00', s)
            yield '/'.join(path), b[s:e].decode(errors='replace'), vabs, ln, val
        elif tok == 9:
            break


def main():
    src, dst = sys.argv[1], sys.argv[2]
    d = bytearray(open(src, 'rb').read())
    print('输入: %s (%d 字节, %d PEB)' % (src, len(d), len(d) // PEB))

    # 1) 收集内核卷 (vol_id == 0) 的 LEB，按 lnum 排序
    lebs = []
    for i in range(len(d) // PEB):
        p = i * PEB
        if d[p:p + 4] != b'UBI#':
            continue
        vid_off = be32(d, p + 16)
        data_off = be32(d, p + 20)
        if d[p + vid_off:p + vid_off + 4] != b'UBI!':
            continue
        vol_id = be32(d, p + vid_off + 8)
        lnum = be32(d, p + vid_off + 12)
        if vol_id != 0:
            continue
        lebs.append((lnum, p + data_off))
    lebs.sort()
    if not lebs:
        print('!! 没找到 vol_id=0 的卷')
        return 1
    leb_size = PEB - (lebs[0][1] - (lebs[0][1] // PEB) * PEB)
    print('  内核卷: %d 个 LEB, LEB 大小 %d' % (len(lebs), leb_size))

    # 2) 拼出卷数据
    vol = bytearray()
    for lnum, off in lebs:
        vol += d[off:off + leb_size]
    if vol[:4] != b'\xd0\x0d\xfe\xed':
        print('!! 卷起始不是 FDT (得到 %r)' % vol[:4])
        return 1
    print('  卷数据 %d 字节, FIT magic OK' % len(vol))

    # 3) 找 flat_dt 子镜像
    dtb_off = dtb_len = None
    types = {}
    for path, name, vabs, ln, val in walk(vol, 0):
        if name == 'type':
            types[path] = val.rstrip(b'\x00').decode()
    for path, name, vabs, ln, val in walk(vol, 0):
        if name == 'data' and types.get(path) == 'flat_dt':
            dtb_off, dtb_len = vabs, ln
            print('  flat_dt: %s  off=0x%x len=%d' % (path, vabs, ln))
    if dtb_off is None:
        print('!! 没找到 flat_dt')
        return 1

    # 4) 改 nand-ecc-strength
    n = 0
    for path, name, vabs, ln, val in walk(vol, dtb_off):
        if name == 'nand-ecc-strength' and ln == 4:
            old = be32(vol, vabs)
            struct.pack_into('>I', vol, vabs, STRENGTH)
            print('  补丁 %s: %d -> %d' % (path, old, STRENGTH))
            n += 1
    if not n:
        print('!! 没找到 nand-ecc-strength')
        return 1

    # 5) 重算 fdt-1 的哈希
    blob = bytes(vol[dtb_off:dtb_off + dtb_len])
    crc = zlib.crc32(blob) & 0xffffffff
    sha = hashlib.sha1(blob).digest()
    fixed = 0
    for path, name, vabs, ln, val in walk(vol, 0):
        if name != 'value' or '/fdt-1/hash-' not in path:
            continue
        algo = None
        for p2, n2, a2, l2, v2 in walk(vol, 0):
            if p2 == path and n2 == 'algo':
                algo = v2.rstrip(b'\x00').decode()
        if algo == 'crc32' and ln == 4:
            struct.pack_into('>I', vol, vabs, crc)
            print('  更新 %s (crc32) = 0x%08x' % (path, crc))
            fixed += 1
        elif algo == 'sha1' and ln == 20:
            vol[vabs:vabs + 20] = sha
            print('  更新 %s (sha1) = %s' % (path, sha.hex()))
            fixed += 1

    # 6) 写回各个 LEB
    for idx, (lnum, off) in enumerate(lebs):
        d[off:off + leb_size] = vol[idx * leb_size:(idx + 1) * leb_size]
    open(dst, 'wb').write(d)
    print('输出: %s (%d 字节)  哈希更新 %d 处' % (dst, len(d), fixed))
    return 0


if __name__ == '__main__':
    sys.exit(main())
