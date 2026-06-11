#!/usr/bin/env python3
"""
TVBox 接口聚合管理系统
- 管理多个 TVBox/影视仓 配置源
- 自动抓取并合并所有启用的源
- 提供单URL导入影视仓
- Web UI 增删改查
"""

import json, os, sys, time, hashlib, threading, re, copy
from pathlib import Path
from collections import OrderedDict
from urllib.parse import urlparse

import requests
from flask import Flask, request, jsonify, render_template, Response, redirect, url_for, send_from_directory


# ── 配置 ──────────────────────────────────────────────────────
DATA_DIR = Path(os.environ.get("TVBOX_DATA_DIR", str(Path.home() / ".tvbox-manager")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = DATA_DIR / "sources.json"
CACHE_DIR = DATA_DIR / "cache"
CACHE_DIR.mkdir(exist_ok=True)
PORT = int(os.environ.get("TVBOX_PORT", "5005"))

app = Flask(__name__)

# ── 默认源列表（qist/tvbox 全部接口 + 各路大佬） ────────────
DEFAULT_SOURCES = [
    {"id": "jsm",     "name": "jsm全家桶",       "url": "https://qist.wyfc.qzz.io/jsm.json",                    "enabled": True},
    {"id": "0821",    "name": "0821 大而全",      "url": "https://qist.wyfc.qzz.io/0821.json",                   "enabled": True},
    {"id": "0822",    "name": "0822 极简配置",    "url": "https://qist.wyfc.qzz.io/0822.json",                   "enabled": False},
    {"id": "0825",    "name": "0825 小而精",      "url": "https://qist.wyfc.qzz.io/0825.json",                   "enabled": False},
    {"id": "0826",    "name": "0826 饭太硬版",    "url": "https://qist.wyfc.qzz.io/0826.json",                   "enabled": False},
    {"id": "0827",    "name": "0827 fongmi版",    "url": "https://qist.wyfc.qzz.io/0827.json",                   "enabled": False},
    {"id": "0828",    "name": "0828 唐三版",      "url": "https://qist.wyfc.qzz.io/0828.json",                   "enabled": False},
    {"id": "0707",    "name": "0707 OK影视专版",  "url": "https://qist.wyfc.qzz.io/0707.json",                   "enabled": False},
    {"id": "js",      "name": "drpy(js)+YouTube", "url": "https://qist.wyfc.qzz.io/js.json",                    "enabled": False},
    {"id": "XBPQ",    "name": "XBPQ 小米小爆脾气","url": "https://qist.wyfc.qzz.io/XBPQ.json",                  "enabled": False},
    {"id": "XYQ",     "name": "XYQ 香雅情",       "url": "https://qist.wyfc.qzz.io/XYQ.json",                   "enabled": False},
    {"id": "cat",     "name": "cat 猫源",         "url": "https://qist.wyfc.qzz.io/cat.json",                   "enabled": False},
    {"id": "fty",     "name": "饭太硬原版",        "url": "https://qist.wyfc.qzz.io/fty.json",                   "enabled": False},
    {"id": "xiaosa",  "name": "潇洒接口",         "url": "https://qist.wyfc.qzz.io/xiaosa/api.json",            "enabled": False},
    {"id": "fantaiying","name": "饭太硬.top",      "url": "http://www.饭太硬.top/tv/",                            "enabled": False},
    {"id": "okjack",  "name": "okjack",           "url": "https://jihulab.com/okcaptain/kko/raw/main/ok.txt",    "enabled": False},
    {"id": "mo_yu_er","name": "摸鱼儿",           "url": "http://我不是.摸鱼儿.top",                                "enabled": False},
    {"id": "nanfeng", "name": "南风",             "url": "https://agit.ai/Yoursmile7/TVBox/raw/branch/master/XC.json", "enabled": False},
    {"id": "qiaoji",  "name": "巧技",             "url": "http://pandown.pro/tvbox/tvbox.json",                  "enabled": False},
    {"id": "ray",     "name": "Ray",              "url": "https://100km.top/0",                                 "enabled": False},
    {"id": "jundie",  "name": "俊于",             "url": "http://home.jundie.top:81/top98.json",                "enabled": False},
    {"id": "jzy",     "name": "橘子柚",           "url": "https://raw.githubusercontent.com/hackyjso/box/main/jzy.txt", "enabled": False},
]

PROXY_MIRRORS = [
    "https://mirror.ghproxy.com/{url}",
    "https://ghproxy.net/{url}",
    "https://gh-proxy.com/{url}",
    "https://github.moeyy.xyz/{url}",
]

# ── 数据载入 ──────────────────────────────────────────────────
def load_sources():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return DEFAULT_SOURCES

def save_sources(sources):
    with open(CONFIG_FILE, "w") as f:
        json.dump(sources, f, ensure_ascii=False, indent=2)

sources = load_sources()
sources_lock = threading.Lock()

# ── 抓取与缓存 ────────────────────────────────
def cache_key(url):
    return hashlib.md5(url.encode()).hexdigest()

def get_cached(url, max_age=600):
    k = cache_key(url)
    cp = CACHE_DIR / f"{k}.json"
    if cp.exists() and time.time() - cp.stat().st_mtime < max_age:
        with open(cp) as f:
            return json.load(f)
    return None

def set_cached(url, data):
    k = cache_key(url)
    with open(CACHE_DIR / f"{k}.json", "w") as f:
        json.dump(data, f)

def fetch_config(url, timeout=8):
    """尝试直接请求或通过镜像代理请求"""
    # 检查缓存
    cached = get_cached(url)
    if cached:
        return cached

    tried = set()
    candidates = [url]

    # 对 GitHub raw 添加镜像
    if "raw.githubusercontent.com" in url or "raw.github.com" in url:
        for mirror_tpl in PROXY_MIRRORS:
            candidates.append(mirror_tpl.format(url=url))
    # 对 jihulab 等也尝试镜像
    if "jihulab.com" in url or "agit.ai" in url:
        for mirror_tpl in PROXY_MIRRORS:
            candidates.append(mirror_tpl.format(url=url))

    # 如果原地址非 https 也尝试一下 https
    if url.startswith("http://"):
        candidates.insert(1, "https://" + url[7:])

    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 TVBox/1.0",
        "Accept": "application/json, text/plain, */*",
    }

    for target_url in candidates:
        if target_url in tried:
            continue
        tried.add(target_url)
        try:
            r = requests.get(target_url, headers=headers, timeout=timeout)
            if r.status_code == 200:
                data = r.json()
                set_cached(url, data)  # 以原始 url 为缓存 key
                return data
        except Exception:
            continue
    return None

def resolve_jar_path(spider_str, source_url):
    """将 jar 相对路径转为完整的 HTTP URL"""
    if not spider_str or spider_str.startswith("http"):
        return spider_str
    # 拼上源的基础 URL
    parts = urlparse(source_url)
    base = f"{parts.scheme}://{parts.netloc}"
    # 如果是 ./jar/spider.jar 格式
    spider_path = spider_str.split(";")[0]
    # 以 source_url 的目录为基准
    source_dir = source_url.rsplit("/", 1)[0]
    if spider_path.startswith("./"):
        return f"{source_dir}/{spider_path[2:]}"
    elif spider_path.startswith("/"):
        return f"{base}{spider_path}"
    else:
        return f"{source_dir}/{spider_path}"

# ── 合并引擎 ───────────────────────────────────
MERGE_KEYS = ["sites", "lives", "parses", "hosts", "flags", "doh", "rules", "ads"]
UNIQUE_KEYS = {
    "sites": "key",
    "lives": "name",
    "parses": "name",
    "doh": "name",
    "rules": "name",
}

def merge_configs(config_list, used_jars=None):
    """将多个配置合并为一个"""
    result = {}
    if used_jars is None:
        used_jars = OrderedDict()

    # 非数组字段：取第一个非空值
    scalar_fields = ["wallpaper"]
    for sf in scalar_fields:
        for cfg, _ in config_list:
            if sf in cfg and cfg[sf]:
                result[sf] = cfg[sf]
                break

    for key in MERGE_KEYS:
        combined = []
        seen = set()
        for cfg, src_url in config_list:
            items = cfg.get(key, [])
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    combined.append(item)
                    continue
                # 去重
                dedup_key = UNIQUE_KEYS.get(key, None)
                if dedup_key:
                    id_val = str(item.get(dedup_key, ""))
                    if id_val and id_val in seen:
                        continue
                    if id_val:
                        seen.add(id_val)
                combined.append(item)
        result[key] = combined

    # spider：收集所有原始 jar 路径（保留 ./ 相对路径，不解析）
    jar_list = []
    jar_keys = {}
    for cfg, src_url in config_list:
        sp = cfg.get("spider", "")
        if sp and sp not in jar_keys:
            jar_keys[sp] = True
            # 只取第一个 ; 前的部分（jar 路径）
            raw_jar = sp.split(";")[0].strip()
            if raw_jar and raw_jar not in jar_list:
                jar_list.append(raw_jar)

    # 多个 jar 用 ; 分隔（TVBox 原生支持多 jar）
    if jar_list:
        result["spider"] = ";".join(jar_list)

    return result

# ── 路由 ──────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html", sources=sources)

@app.route("/api/sources")
def api_get_sources():
    with sources_lock:
        return jsonify(sources)

@app.route("/api/sources", methods=["POST"])
def api_add_source():
    data = request.json
    if not data or not data.get("url"):
        return jsonify({"error": "url required"}), 400
    import uuid
    new_source = {
        "id": data.get("id", uuid.uuid4().hex[:8]),
        "name": data.get("name", data["url"]),
        "url": data["url"],
        "enabled": data.get("enabled", True),
    }
    with sources_lock:
        # 去重
        for s in sources:
            if s["url"] == new_source["url"]:
                return jsonify({"error": "URL already exists", "source": s}), 409
        sources.append(new_source)
        save_sources(sources)
    return jsonify(new_source), 201

@app.route("/api/sources/<source_id>", methods=["PUT"])
def api_update_source(source_id):
    data = request.json or {}
    with sources_lock:
        for s in sources:
            if s["id"] == source_id:
                if "name" in data:
                    s["name"] = data["name"]
                if "url" in data:
                    s["url"] = data["url"]
                if "enabled" in data:
                    s["enabled"] = data["enabled"]
                save_sources(sources)
                return jsonify(s)
        return jsonify({"error": "not found"}), 404

@app.route("/api/sources/<source_id>", methods=["DELETE"])
def api_delete_source(source_id):
    with sources_lock:
        global sources
        new_list = [s for s in sources if s["id"] != source_id]
        if len(new_list) == len(sources):
            return jsonify({"error": "not found"}), 404
        sources = new_list
        save_sources(sources)
    return jsonify({"status": "deleted"})

@app.route("/api/sources/toggle", methods=["POST"])
def api_toggle_source():
    data = request.json
    source_id = data.get("id")
    enabled = data.get("enabled")
    with sources_lock:
        for s in sources:
            if s["id"] == source_id:
                s["enabled"] = enabled
                save_sources(sources)
                return jsonify(s)
    return jsonify({"error": "not found"}), 404

@app.route("/api/status")
def api_status():
    """查看每个源的抓取状态"""
    results = []
    with sources_lock:
        for s in sources:
            st = {"id": s["id"], "name": s["name"], "url": s["url"], "enabled": s["enabled"]}
            cached = get_cached(s["url"])
            st["cached"] = cached is not None
            st["sites_count"] = len(cached.get("sites", [])) if cached else 0
            st["lives_count"] = len(cached.get("lives", [])) if cached else 0
            results.append(st)
    return jsonify(results)

@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    """手动强制刷新缓存"""
    source_id = (request.json or {}).get("id")
    cleared = 0
    with sources_lock:
        for s in sources:
            if source_id and s["id"] != source_id:
                continue
            k = cache_key(s["url"])
            cp = CACHE_DIR / f"{k}.json"
            if cp.exists():
                cp.unlink()
                cleared += 1
    return jsonify({"status": "cache cleared", "count": cleared})

@app.route("/jar/<path:path>")
def proxy_jar(path):
    """代理转发 jar/css/js 等静态资源，防止电视无法访问外链 CDN
       路径格式: /jar/<source>/<file>  或 /jar/<file>
       例如: /jar/qist.jarmirror.com/jar/spider.jar
             原始 jar 在 spider 字段里是 ./jar/spider.jar，对应 CDN 路径
    """
    # 尝试从多个镜像源下载
    cdn_bases = [
        "https://qist.wyfc.qzz.io",
        "https://cdn.jsdelivr.net/gh/qist/tvbox",
        "https://raw.githubusercontent.com/qist/tvbox/master",
    ]
    headers_req = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 TVBox/1.0",
        "Referer": "https://github.com/qist/tvbox",
    }
    for base in cdn_bases:
        jar_url = f"{base}/jar/{path}"
        try:
            r = requests.get(jar_url, headers=headers_req, timeout=10, stream=True)
            if r.status_code == 200:
                resp = Response(r.iter_content(chunk_size=65536), status=200)
                resp.headers["Content-Type"] = r.headers.get("Content-Type", "application/java-archive")
                resp.headers["Cache-Control"] = "max-age=3600"
                resp.headers["Access-Control-Allow-Origin"] = "*"
                return resp
        except:
            continue
    return "JAR not found", 404

@app.route("/single/<source_id>")
def single_source(source_id):
    """直接代理单个源配置，不合并（避免多 jar 冲突）"""
    with sources_lock:
        target = next((s for s in sources if s["id"] == source_id and s["enabled"]), None)
    if not target:
        # 尝试找同名
        with sources_lock:
            target = next((s for s in sources if s["id"] == source_id), None)
        if not target:
            return jsonify({"error": "source not found"}), 404

    data = fetch_config(target["url"])
    if not data:
        return jsonify({"error": "fetch failed"}), 502

    # 替换 spider jar 路径 -> 本地代理
    sp = data.get("spider", "")
    if sp:
        parts = sp.split(";")
        jar_path = parts[0]
        if jar_path.startswith("./"):
            # ./jar/spider.jar → 取最后一段文件名 spider.jar
            file_name = jar_path.rsplit("/", 1)[-1]
            parts[0] = f"http://192.168.31.8:{PORT}/jar/{file_name}"
            data["spider"] = ";".join(parts)

    return Response(
        json.dumps(data, ensure_ascii=False),
        content_type="application/json; charset=utf-8",
        headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-cache"}
    )

@app.route("/tvbox.json")
@app.route("/merge.json")
def merged_config():
    """✨ 核心：合并所有启用源，返回 TVBox 格式 JSON
       spider jar 全部走本地代理，防止外链不可达"""
    threads = []
    results = {}

    def fetch_and_store(url):
        data = fetch_config(url)
        results[url] = data

    with sources_lock:
        enabled = [s for s in sources if s["enabled"]]

    for s in enabled:
        t = threading.Thread(target=fetch_and_store, args=(s["url"],))
        threads.append(t)
        t.start()

    for t in threads:
        t.join(timeout=30)

    config_list = []
    for s in enabled:
        data = results.get(s["url"])
        if data:
            config_list.append((data, s["url"]))
            cached = get_cached(s["url"])
            if not cached:
                set_cached(s["url"], data)

    if not config_list:
        return jsonify({"sites": [], "lives": [], "parses": [], "spider": "", "rules": [], "ads": []})

    merged = merge_configs(config_list)

    # 替换 spider jar 路径为本地代理
    sp = merged.get("spider", "")
    if sp:
        jar_parts = []
        for segment in sp.split(";"):
            seg = segment.strip()
            if not seg:
                continue
            # 如果是 ./jar/spider.jar → 取文件名 → /jar/spider.jar
            if seg.startswith("./"):
                file_name = seg.rsplit("/", 1)[-1]
                jar_parts.append(f"http://192.168.31.8:{PORT}/jar/{file_name}")
            elif seg.startswith("/"):
                file_name = seg.rsplit("/", 1)[-1]
                jar_parts.append(f"http://192.168.31.8:{PORT}/jar/{file_name}")
            else:
                jar_parts.append(seg)
        if jar_parts:
            merged["spider"] = ";".join(jar_parts)

    return Response(
        json.dumps(merged, ensure_ascii=False),
        content_type="application/json; charset=utf-8",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "no-cache",
        }
    )

@app.route("/raw/<source_id>")
def raw_local(source_id):
    """直接读取 static/clean/<id>.json 并处理 jar 代理路径"""
    clean_path = Path(__file__).parent / "static" / "clean" / f"{source_id}.json"
    if not clean_path.exists():
        return jsonify({"error": "clean file not found"}), 404
    with open(clean_path, encoding="utf-8") as f:
        data = json.load(f)

    sp = data.get("spider", "")
    if sp:
        parts_new = []
        for seg in sp.split(";"):
            seg = seg.strip()
            if not seg:
                continue
            if seg.startswith("./") or seg.startswith("/"):
                file_name = seg.rsplit("/", 1)[-1]
                parts_new.append(f"http://192.168.31.8:{PORT}/jar/{file_name}")
            else:
                parts_new.append(seg)
        if parts_new:
            data["spider"] = ";".join(parts_new)

    return Response(json.dumps(data, ensure_ascii=False),
                    content_type="application/json; charset=utf-8",
                    headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-cache"})

@app.route("/multi")
@app.route("/index.json")
@app.route("/channels.json")
def multi_source_index():
    """多仓接口格式：{urls: [{url, name}, ...]}
       影视仓导入后显示多个源供选择，不合并
       本地清理文件优先用 /raw/<id>，否则用 /single/<id>"""
    with sources_lock:
        enabled = [s for s in sources if s["enabled"]]

    static_dir = Path(__file__).parent / "static" / "clean"
    urls = []
    for s in enabled:
        local_file = static_dir / f"{s['id']}.json"
        if local_file.exists():
            url = f"http://192.168.31.8:{PORT}/raw/{s['id']}"
        else:
            url = f"http://192.168.31.8:{PORT}/single/{s['id']}"
        urls.append({"url": url, "name": s["name"]})

    result = {"urls": urls}
    return Response(json.dumps(result, ensure_ascii=False, indent=2),
                    content_type="application/json; charset=utf-8",
                    headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-cache"})

@app.route("/m3u")
def m3u_export():
    """导出直播源为 M3U 格式（部分播放器用）"""
    data = fetch_config(sources[0]["url"]) if sources else None
    lines = ['#EXTM3U']
    if data and "lives" in data:
        for live in data["lives"]:
            name = live.get("name", "Unknown")
            url = live.get("url", "")
            logo = live.get("logo", "")
            if logo:
                lines.append(f'#EXTINF:-1 tvg-logo="{logo}",{name}')
            else:
                lines.append(f'#EXTINF:-1,{name}')
            lines.append(url)
    return Response("\n".join(lines), content_type="audio/x-mpegurl")

# ── 入口 ──────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"\n{'='*50}")
    print(f"  📺 TVBox 接口聚合管理系统")
    print(f"  🌐 Web管理: http://192.168.31.8:{PORT}")
    print(f"  📡 影视仓导入: http://192.168.31.8:{PORT}/tvbox.json")
    print(f"  🗑️  同名: http://192.168.31.8:{PORT}/merge.json")
    print(f"  📋 源状态: http://192.168.31.8:{PORT}/api/status")
    print(f"{'='*50}\n")
    app.run(host="0.0.0.0", port=PORT, debug=False)
