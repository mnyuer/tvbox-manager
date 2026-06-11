#!/usr/bin/env python3
"""
GitHub Actions update script for TVBox manager.
Downloads, cleans JSON sources, fetches JARs, generates multi.json.
"""
import json, os, urllib.request, re, pathlib, sys

GH_USER = os.environ.get("GH_USER", "mnyuer")
REPO = os.environ.get("REPO", "tvbox-manager")
JAR_BASE = f"https://{GH_USER}.github.io/{REPO}/jar"
RAW_BASE = f"https://{GH_USER}.github.io/{REPO}/static/clean"

WORK = pathlib.Path(".")
CLEAN = WORK / "static" / "clean"
JAR_DIR = WORK / "static" / "jar"
CLEAN.mkdir(parents=True, exist_ok=True)
JAR_DIR.mkdir(parents=True, exist_ok=True)

# (id, url, display_name)
SOURCES = [
    ("jsm",  "https://qist.wyfc.qzz.io/jsm.json",  "jsm全家桶"),
    ("0821", "https://qist.wyfc.qzz.io/0821.json", "0821 大而全"),
]

JARS = [
    ("spider.jar", "https://qist.wyfc.qzz.io/jar/spider.jar"),
    ("fan.txt",    "https://qist.wyfc.qzz.io/jar/fan.txt"),
]

# Remove stale files from previous runs
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

def clean_txt(txt):
    txt = re.sub(r'/\*.*?\*/', '', txt, flags=re.DOTALL)
    txt = re.sub(r'//[^\n]*', '', txt)
    txt = re.sub(r',\s*([\]}])', r'\1', txt)
    return txt.strip()

def fetch(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=timeout).read()

# ── Clean JSON sources ──
for sid, url, _ in SOURCES:
    print(f"=== {sid} ===")
    try:
        raw = fetch(url).decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  download FAILED: {e}")
        continue

    try:
        d = json.loads(raw)
    except:
        try:
            d = json.loads(clean_txt(raw))
        except Exception as e:
            print(f"  parse FAILED: {e}")
            continue

    # Rewrite spider jar path -> GitHub Pages
    sp = d.get("spider", "")
    if sp:
        parts = [p.strip() for p in sp.split(";")]
        new_parts = []
        for p in parts:
            if p.startswith("http"):
                new_parts.append(p)
            elif p.startswith("./") or p.startswith("/"):
                fname = p.rsplit("/", 1)[-1]
                new_parts.append(f"{JAR_BASE}/{fname}")
            else:
                new_parts.append(p)
        d["spider"] = ";".join(new_parts)

    (CLEAN / f"{sid}.json").write_text(json.dumps(d, ensure_ascii=False, indent=2))
    print(f"  saved: {len(d.get('sites',[]))} sites")

# ── Download JARs ──
for fname, url in JARS:
    try:
        data = fetch(url, timeout=30)
        (JAR_DIR / fname).write_bytes(data)
        print(f"JAR {fname} ({len(data)} bytes)")
    except Exception as e:
        print(f"JAR {fname} FAILED: {e}")

# ── Generate multi.json ──
names_map = {sid: sname for sid, _, sname in SOURCES}
urls = []
for f in sorted(CLEAN.glob("*.json")):
    sid = f.stem
    name = names_map.get(sid, sid)
    urls.append({"url": f"{RAW_BASE}/{sid}.json", "name": name})

(WORK / "multi.json").write_text(json.dumps({"urls": urls}, ensure_ascii=False, indent=2))
print(f"\nmulti.json: {len(urls)} sources")

# ── Mirror Migu live source (M3U) ──
MIGU_URL = "https://raw.githubusercontent.com/develop202/migu_video/main/interface.txt"
print("\n=== Mirror Migu live source ===")
try:
    req = urllib.request.Request(MIGU_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()
    (WORK / "migu.m3u").write_bytes(data)
    ch_count = sum(1 for l in data.decode("utf-8", errors="replace").splitlines() if l.startswith("#EXTINF"))
    print(f"  migu.m3u: {len(data)} bytes, {ch_count} channels")
except Exception as e:
    print(f"  Migu mirror failed: {e}")