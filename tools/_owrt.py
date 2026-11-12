#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run shell commands on the OpenWrt initramfs over SSH.

usage: python _owrt.py "cmd1" "cmd2" ...
env: OW_HOST (default 192.168.1.1), OW_USER (root), OW_PASS (empty)
"""
import os
import sys

import paramiko

HOST = os.environ.get('OW_HOST', '192.168.1.1')
USER = os.environ.get('OW_USER', 'root')
PASS = os.environ.get('OW_PASS', '')


def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, port=22, username=USER, password=PASS,
              allow_agent=False, look_for_keys=False,
              timeout=12, banner_timeout=20, auth_timeout=20)
    return c


def run(c, cmd, timeout=120):
    chan = c.get_transport().open_session()
    chan.settimeout(timeout)
    chan.exec_command(cmd)
    out = b''
    while True:
        if chan.recv_ready():
            out += chan.recv(65536)
        elif chan.exit_status_ready():
            while chan.recv_ready():
                out += chan.recv(65536)
            break
    err = b''
    while chan.recv_stderr_ready():
        err += chan.recv_stderr(65536)
    rc = chan.recv_exit_status()
    chan.close()
    return rc, out.decode(errors='replace'), err.decode(errors='replace')


def main():
    cmds = sys.argv[1:]
    if not cmds:
        cmds = ['cat /etc/openwrt_release']
    try:
        c = connect()
    except Exception as e:
        print('SSH 连接失败: %s' % e)
        return 1
    print('SSH 已连接 %s@%s\n' % (USER, HOST))
    for cmd in cmds:
        print('=' * 68)
        print('>>> %s' % cmd)
        print('=' * 68)
        rc, out, err = run(c, cmd)
        if out.strip():
            print(out.rstrip())
        if err.strip():
            print('[stderr] ' + err.rstrip())
        print('[exit=%s]\n' % rc)
    c.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
