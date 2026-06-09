#!/usr/bin/env python3
"""清理 TVBox JSON：去除 // 注释、/*...*/、尾逗号，输出纯 JSON"""
import re, sys, json

BLOCK_CMT = re.compile(r'/\*.*?\*/', re.DOTALL)
LINE_CMT  = re.compile(r'//[^\n]*')
TRAIL_CMA = re.compile(r',\s*([}\]])')

def clean(txt):
    txt = BLOCK_CMT.sub('', txt)
    txt = LINE_CMT.sub('', txt)
    txt = TRAIL_CMA.sub(r'\1', txt)
    return txt.strip()

if len(sys.argv) == 3 and sys.argv[1] == '-o':
    out = open(sys.argv[2], 'w')
    inp = sys.stdin
else:
    out = sys.stdout
    inp = sys.stdin

data = clean(inp.read())
json.dump(json.loads(data), out, ensure_ascii=False, indent=2)
