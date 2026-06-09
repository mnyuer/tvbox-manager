#!/usr/bin/env bash
# 每天检查并清理需要的源码（去除 JSON 注释）
# 当前只清理 XYQ，后续可自行在 IDS 列表中添加更多 ID
IDS=("XYQ")
BASE_URL="https://qist.wyfc.qzz.io"
STATIC_DIR="/home/mnxym/projects/tvbox-manager/static/clean"
mkdir -p "$STATIC_DIR"
for ID in "${IDS[@]}"; do
    URL="$BASE_URL/${ID}.json"
    TMP="/tmp/${ID}_raw.json"
    OUT="$STATIC_DIR/${ID}.json"
    echo "Fetching $URL → $TMP"
    curl -sL "$URL" -o "$TMP"
    if [[ $? -ne 0 || ! -s "$TMP" ]]; then
        echo "⚠️  下载失败或文件为空: $URL"
        continue
    fi
    python3 - <<PY
import re, json, pathlib, sys
raw_path = pathlib.Path("$TMP")
out_path = pathlib.Path("$OUT")
text = raw_path.read_text(encoding='utf-8').replace('\r','')
# 删除行注释 //
text = re.sub(r'(?m)^\s*//.*\n?', '', text)
# 删除块注释 /* */
text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
# 删除尾随逗号
text = re.sub(r',\s*([}\]])', r'\1', text)
data = json.loads(text)
out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
PY
    if [[ $? -eq 0 ]]; then
        echo "✅ $ID 已更新并清理至 $OUT"
    else
        echo "❌ $ID 清理失败"
    fi
done
