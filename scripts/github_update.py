#!/usr/bin/env python3
"""
GitHub Actions update script for TVBox manager.
Downloads, cleans JSON sources, fetches JARs, generates multi.json.

2026-10-15 修复：
  1. 上游源改为 qist/tvbox 的 GitHub 原生 raw 地址（Actions runner 访问自家域名最稳），
     Cloudflare 前端 qist.wyfc.qzz.io 降为兜底。原脚本用 qzz.io 作为唯一源，
     在 Actions 里一直下载失败并被 except 静默吞掉 —— 这是仓库 4 个月无提交的根因。
  2. 加了重试与多源回退。
  3. 不再静默失败：写 run_status.txt，由 workflow 最后一步决定是否把任务标红。
"""
import json, os, re, pathlib, sys, time, urllib.request

GH_USER = os.environ.get("GH_USER", "mnyuer")
REPO = os.environ.get("REPO", "tvbox-manager")
JAR_BASE = f"https://{GH_USER}.github.io/{REPO}/jar"
RAW_BASE = f"https://{GH_USER}.github.io/{REPO}/static/clean"

WORK = pathlib.Path(".")
CLEAN = WORK / "static" / "clean"
JAR_DIR = WORK / "static" / "jar"
CLEAN.mkdir(parents=True, exist_ok=True)
JAR_DIR.mkdir(parents=True, exist_ok=True)

UA = {"User-Agent": "Mozilla/5.0 (compatible; tvbox-manager/1.0)"}

UPSTREAM_RAW = "https://raw.githubusercontent.com/qist/tvbox/master"
UPSTREAM_MIRROR = "https://qist.wyfc.qzz.io"


def urls(rel):
    return [f"{UPSTREAM_RAW}/{rel}", f"{UPSTREAM_MIRROR}/{rel}"]


# (id, [候选 url, ...], display_name)
SOURCES = [
    ("jsm",  urls("jsm.json"),  "jsm全家桶"),
    ("0821", urls("0821.json"), "0821 大而全"),
]
# (文件名, [候选 url, ...])
JARS = [
    ("spider.jar", urls("jar/spider.jar")),
    ("fan.txt",    urls("jar/fan.txt")),
]
MIGU_URLS = ["https://raw.githubusercontent.com/develop202/migu_video/main/interface.txt"]

problems = []


def fetch(url, timeout=30, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            return urllib.request.urlopen(req, timeout=timeout).read()
        except Exception as e:
            last = e
            if i < tries - 1:
                time.sleep(2 * (i + 1))
    raise last


def fetch_any(candidates, timeout=30):
    errs = []
    for u in candidates:
        try:
            data = fetch(u, timeout=timeout)
            print(f"  ok   <- {u}  ({len(data)} bytes)")
            return data
        except Exception as e:
            print(f"  FAIL <- {u}  ({e})")
            errs.append(f"{u} -> {e}")
    raise RuntimeError(" | ".join(errs))


def clean_txt(txt):
    txt = re.sub(r'/\*.*?\*/', '', txt, flags=re.DOTALL)
    txt = re.sub(r'//[^\n]*', '', txt)
    txt = re.sub(r',\s*([\]}])', r'\1', txt)
    return txt.strip()


# ── 清理上一轮的陈旧文件 ──
SOURCE_IDS = {s[0] for s in SOURCES}
for f in list(CLEAN.glob("*.json")):
    if f.stem not in SOURCE_IDS:
        f.unlink()
        print(f"  (removed stale {f.name})")
JAR_NAMES = {j[0] for j in JARS}
for f in list(JAR_DIR.iterdir()):
    if f.name not in JAR_NAMES:
        f.unlink()
        print(f"  (removed stale jar/{f.name})")

# ── 抓取并清洗 JSON 源 ──
for sid, cands, _ in SOURCES:
    print(f"=== {sid} ===")
    try:
        raw = fetch_any(cands).decode("utf-8", errors="replace")
    except Exception as e:
        problems.append(f"source {sid}: {e}")
        print(f"  download FAILED: {e}")
        continue

    try:
        d = json.loads(raw)
    except Exception:
        try:
            d = json.loads(clean_txt(raw))
        except Exception as e:
            problems.append(f"source {sid}: JSON parse failed: {e}")
            print(f"  parse FAILED: {e}")
            continue

    # 把 spider 的本地相对路径改写成 GitHub Pages 地址
    sp = d.get("spider", "")
    if sp:
        new_parts = []
        for p in [x.strip() for x in sp.split(";")]:
            if p.startswith("http"):
                new_parts.append(p)
            elif p.startswith("./") or p.startswith("/"):
                fname = p.rsplit("/", 1)[-1]
                new_parts.append(f"{JAR_BASE}/{fname}")
            else:
                new_parts.append(p)
        d["spider"] = ";".join(new_parts)

    if not d.get("sites"):
        problems.append(f"source {sid}: sites 为空")
        print("  WARN: sites 为空，跳过写入")
        continue

    (CLEAN / f"{sid}.json").write_text(json.dumps(d, ensure_ascii=False, indent=2))
    print(f"  saved: {len(d.get('sites', []))} sites")

# ── 抓取 JAR / 规则文件 ──
for fname, cands in JARS:
    try:
        data = fetch_any(cands, timeout=60)
        (JAR_DIR / fname).write_bytes(data)
        print(f"JAR {fname}: {len(data)} bytes")
    except Exception as e:
        problems.append(f"jar {fname}: {e}")
        print(f"JAR {fname} FAILED: {e}")

# ── 生成 multi.json ──
names_map = {sid: sname for sid, _, sname in SOURCES}
urls_out = []
for f in sorted(CLEAN.glob("*.json")):
    sid = f.stem
    urls_out.append({"url": f"{RAW_BASE}/{sid}.json", "name": names_map.get(sid, sid)})

(WORK / "multi.json").write_text(json.dumps({"urls": urls_out}, ensure_ascii=False, indent=2))
print(f"\nmulti.json: {len(urls_out)} sources")

# ── 镜像 Migu 直播源 ──
# 注意：develop202/migu_video 已改版，interface.txt 现在只剩一个 #EXTM3U 头（约 469 字节、
# 0 个频道），频道由该仓库自己的服务动态生成。直接写入会把已有的完整播放列表覆盖成空文件，
# 所以这里加一道闸：频道数过少就跳过写入并上报，保护现有 migu.m3u。
print("\n=== Mirror Migu live source ===")
MIN_CHANNELS = 10
try:
    data = fetch_any(MIGU_URLS, timeout=60)
    text = data.decode("utf-8", errors="replace")
    ch = sum(1 for l in text.splitlines() if l.startswith("#EXTINF"))
    if ch < MIN_CHANNELS:
        problems.append(
            f"migu: 上游 interface.txt 疑似改版，仅 {ch} 个频道（{len(data)} bytes），已跳过写入以保护现有 migu.m3u"
        )
        print(f"  SKIP: 仅 {ch} 个频道（阈值 {MIN_CHANNELS}），保留现有 migu.m3u")
    else:
        (WORK / "migu.m3u").write_bytes(data)
        print(f"  migu.m3u: {len(data)} bytes, {ch} channels")
except Exception as e:
    problems.append(f"migu: {e}")
    print(f"  Migu mirror failed: {e}")

# ── 结果落盘，交由 workflow 决定是否标红 ──
status = "OK" if not problems else "FAILED\n" + "\n".join(problems)
(WORK / "run_status.txt").write_text(status + "\n")
print("\n=== 结果 ===")
print(status)
sys.exit(0)
