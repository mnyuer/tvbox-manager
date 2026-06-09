#!/usr/bin/env python3
"""
GitHub Actions update script for TVBox manager.
Downloads, cleans JSON sources, fetches JARs, generates multi.json.
"""
import json, os, urllib.request, re, pathlib, sys

GH_USER = os.environ.get("GH_USER", "mnyuer")
REPO = os.environ.get("REPO", "tvbox-manager")
JAR_BASE = f"https://{GH_USER}.github.io/{REPO}/jar"
RAW_BASE = f"https://raw.githubusercontent.com/{GH_USER}/{REPO}/main/static/clean"

WORK = pathlib.Path(".")
CLEAN = WORK / "static" / "clean"
JAR_DIR = WORK / "static" / "jar"
CLEAN.mkdir(parents=True, exist_ok=True)
JAR_DIR.mkdir(parents=True, exist_ok=True)

SOURCES = [
    ("jsm",     "https://qist.wyfc.qzz.io/jsm.json"),
    ("0821",    "https://qist.wyfc.qzz.io/0821.json"),
    ("0826",    "https://qist.wyfc.qzz.io/0826.json"),
    ("0827",    "https://qist.wyfc.qzz.io/0827.json"),
    ("0707",    "https://qist.wyfc.qzz.io/0707.json"),
    ("js",      "https://qist.wyfc.qzz.io/js.json"),
    ("XYQ",     "https://qist.wyfc.qzz.io/XYQ.json"),
    ("fty",     "https://qist.wyfc.qzz.io/fty.json"),
    ("xiaosa",  "https://qist.wyfc.qzz.io/xiaosa/api.json"),
    ("mo_yu_er","https://6800.kstore.vip/fish.json"),
    ("jundie",  "http://home.jundie.top:81/top98.json"),
]

JARS = [
    ("spider.jar",      "https://qist.wyfc.qzz.io/jar/spider.jar"),
    ("custom_spider.jar","https://qist.wyfc.qzz.io/jar/custom_spider.jar"),
    ("pg.jar",           "https://qist.wyfc.qzz.io/jar/pg.jar"),
    ("XYQ.jar",          "https://qist.wyfc.qzz.io/jar/XYQ.jar"),
    ("fan.txt",          "https://qist.wyfc.qzz.io/jar/fan.txt"),
    ("top98_1.jar",      "http://home.jundie.top:81/jar/top98_1.jar"),
    ("fish06090225.jar", "https://tc-new.z.wiki/autoupload/iYHTWVx6T8RrCmqdGD6MOdiO_OyvX7mIgxFBfDMDErs/20260609/ieKK/fish06090225.jar"),
]

def clean_txt(txt):
    txt = re.sub(r'/\*.*?\*/', '', txt, flags=re.DOTALL)
    txt = re.sub(r'//[^\n]*', '', txt)
    txt = re.sub(r',\s*([\]}])', r'\1', txt)
    return txt.strip()

def fetch(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=timeout).read()

# ── Clean JSON sources ──
for sid, url in SOURCES:
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

    # Rewrite spider
    sp = d.get("spider", "")
    if sp:
        jname = sp.split(";")[0].strip()
        if not jname.startswith("http"):
            base = jname.rsplit("/", 1)[-1]
            d["spider"] = f"{JAR_BASE}/{base}"
            rest = sp.split(";")[1:] if ";" in sp else []
            if rest:
                d["spider"] += ";" + ";".join(rest)

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
urls = []
for f in sorted(CLEAN.glob("*.json")):
    sid = f.stem
    try:
        d = json.loads(f.read_text())
        name = d.get("name", sid)
    except:
        name = sid
    # Find original source name from SOURCES
    for sid2, _ in SOURCES:
        if sid2 == sid:
            name = next((n for n, u in SOURCES if u.endswith(f"/{sid}.json") or sid in u), sid)
            break
    urls.append({"url": f"{RAW_BASE}/{sid}.json", "name": name})

(WORK / "multi.json").write_text(json.dumps({"urls": urls}, ensure_ascii=False, indent=2))
print(f"\nmulti.json: {len(urls)} sources")
