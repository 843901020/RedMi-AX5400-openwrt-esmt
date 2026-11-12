#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Push a local directory to a GitHub repo via the Git Data API.

Used when `git push` can't get through the local proxy but api.github.com is
reachable. Creates blobs -> tree -> commit -> ref in one shot, so the result is
a single clean commit (not one per file).

usage: python _ghpush.py <repo_dir> <owner/repo> <token> [branch] [message]
"""
import base64
import json
import os
import sys
import urllib.request

API = 'https://api.github.com'
SKIP_DIRS = {'.git', '__pycache__', 'node_modules'}
SKIP_EXT = {'.bin', '.ubi', '.zip', '.log'}


def call(method, path, token, payload=None):
    url = API + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header('Authorization', 'Bearer ' + token)
    req.add_header('Accept', 'application/vnd.github+json')
    req.add_header('User-Agent', 'ghpush/1.0')
    if data:
        req.add_header('Content-Type', 'application/json')
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read()
        return json.loads(body) if body.strip() else {}


def collect(root):
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() in SKIP_EXT:
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root).replace('\\', '/')
            out.append((rel, full))
    return sorted(out)


def main():
    root, repo, token = sys.argv[1], sys.argv[2], sys.argv[3]
    branch = sys.argv[4] if len(sys.argv) > 4 else 'main'
    msg = sys.argv[5] if len(sys.argv) > 5 else 'Update from local'

    files = collect(root)
    print('待上传 %d 个文件' % len(files))

    tree = []
    for rel, full in files:
        raw = open(full, 'rb').read()
        blob = call('POST', '/repos/%s/git/blobs' % repo, token, {
            'content': base64.b64encode(raw).decode(),
            'encoding': 'base64',
        })
        tree.append({'path': rel, 'mode': '100644', 'type': 'blob', 'sha': blob['sha']})
        print('  blob %-32s %6d B  %s' % (rel, len(raw), blob['sha'][:10]))

    t = call('POST', '/repos/%s/git/trees' % repo, token, {'tree': tree})
    print('tree  %s' % t['sha'][:12])

    c = call('POST', '/repos/%s/git/commits' % repo, token, {
        'message': msg, 'tree': t['sha'], 'parents': [],
    })
    print('commit %s' % c['sha'][:12])

    try:
        call('POST', '/repos/%s/git/refs' % repo, token, {
            'ref': 'refs/heads/' + branch, 'sha': c['sha'],
        })
        print('分支 %s 已创建' % branch)
    except urllib.error.HTTPError as e:
        if e.code == 422:      # 已存在 -> 强制更新
            call('PATCH', '/repos/%s/git/refs/heads/%s' % (repo, branch), token, {
                'sha': c['sha'], 'force': True,
            })
            print('分支 %s 已更新' % branch)
        else:
            raise
    print('\n完成: https://github.com/%s/tree/%s' % (repo, branch))


if __name__ == '__main__':
    main()
