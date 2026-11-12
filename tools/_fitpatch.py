#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Patch nand-ecc-strength inside an OpenWrt FIT image and fix its hash nodes.

The AX5400 DTB hardcodes nand-ecc-strength = <8>, which needs 128 bytes of OOB.
Units with an ESMT F50D1G41LB (64-byte OOB) need <4>.  The property is a single
u32 cell, so the blob size never changes - only the value plus the FIT hashes.

usage: python _fitpatch.py <in.bin> <out.bin> [strength]
"""
import hashlib
import struct
import sys
import zlib

STRENGTH = int(sys.argv[3]) if len(sys.argv) > 3 else 4


def be32(b, o):
    return struct.unpack('>I', b[o:o + 4])[0]


def fdt_header(b, off):
    f = struct.unpack('>10I', b[off:off + 40])
    return dict(magic=f[0], total=f[1], off_struct=f[2], off_strings=f[3],
                off_rsv=f[4], ver=f[5], lastver=f[6], boot=f[7],
                size_str=f[8], size_struct=f[9])


def walk(b, off):
    """Yield (path, propname, value_abs_offset, length, value) for one FDT."""
    h = fdt_header(b, off)
    if h['magic'] != 0xd00dfeed:
        raise ValueError('not an FDT at 0x%x' % off)
    p = off + h['off_struct']
    end = p + h['size_struct']
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
            s = off + h['off_strings'] + noff
            e = b.index(b'\x00', s)
            name = b[s:e].decode(errors='replace')
            yield '/'.join(path), name, vabs, ln, val
        elif tok == 4:
            continue
        elif tok == 9:
            break


def main():
    src, dst = sys.argv[1], sys.argv[2]
    d = bytearray(open(src, 'rb').read())
    print('输入: %s (%d 字节)' % (src, len(d)))

    # 1) 找到 FIT 里的 flat_dt 子镜像
    dtb_off = dtb_len = None
    for path, name, vabs, ln, val in walk(d, 0):
        if path.startswith('/images/') and name == 'data' and '/hash' not in path:
            # 该节点是 kernel-1 还是 fdt-1，看同级 type
            node = path
            typ = None
            for p2, n2, a2, l2, v2 in walk(d, 0):
                if p2 == node and n2 == 'type':
                    typ = v2.rstrip(b'\x00').decode()
            if typ == 'flat_dt':
                dtb_off, dtb_len = vabs, ln
                print('  找到 flat_dt: %s  offset=0x%x len=%d' % (node, vabs, ln))
    if dtb_off is None:
        print('!! 没找到 flat_dt 子镜像')
        return 1

    # 2) 改 nand-ecc-strength
    changed = 0
    for path, name, vabs, ln, val in walk(d, dtb_off):
        if name == 'nand-ecc-strength' and ln == 4:
            old = be32(d, vabs)
            struct.pack_into('>I', d, vabs, STRENGTH)
            print('  补丁 %s: nand-ecc-strength %d -> %d  (abs 0x%x)' % (path, old, STRENGTH, vabs))
            changed += 1
    if not changed:
        print('!! 没找到 nand-ecc-strength')
        return 1

    # 3) 重算 fdt-1 的 hash-1(crc32) / hash-2(sha1)
    blob = bytes(d[dtb_off:dtb_off + dtb_len])
    crc = zlib.crc32(blob) & 0xffffffff
    sha = hashlib.sha1(blob).digest()
    print('  新 crc32 = 0x%08x' % crc)
    print('  新 sha1  = %s' % sha.hex())

    fixed = 0
    for path, name, vabs, ln, val in walk(d, 0):
        if not path.endswith('/hash-1') and not path.endswith('/hash-2'):
            continue
        parent = path.rsplit('/', 1)[0]
        # 只处理 fdt-1 的哈希
        if not parent.endswith('/fdt-1'):
            continue
        algo = None
        for p2, n2, a2, l2, v2 in walk(d, 0):
            if p2 == path and n2 == 'algo':
                algo = v2.rstrip(b'\x00').decode()
        if name == 'value' and algo == 'crc32' and ln == 4:
            struct.pack_into('>I', d, vabs, crc)
            print('  更新 %s(crc32) -> 0x%08x' % (path, crc))
            fixed += 1
        elif name == 'value' and algo == 'sha1' and ln == 20:
            d[vabs:vabs + 20] = sha
            print('  更新 %s(sha1)' % path)
            fixed += 1

    open(dst, 'wb').write(d)
    print('输出: %s (%d 字节)  哈希更新 %d 处' % (dst, len(d), fixed))
    return 0


if __name__ == '__main__':
    sys.exit(main())
