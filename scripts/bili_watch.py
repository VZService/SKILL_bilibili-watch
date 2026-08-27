#!/usr/bin/env python3
"""
bili_watch.py - 把 B 站视频变成可阅读的文本，交给 AI 阅读。

用法:
    python bili_watch.py <BVID 或视频链接> [--browser chrome] [--asr]

工作模式:
    1. 优先用你本机浏览器登录态抓 AI 字幕(最干净、最完整)。
    2. 没有字幕时退而抓弹幕(无需登录，但碎片化)。
    3. 加 --asr 且本机装了 ffmpeg + whisper，可把音频转写成文字(覆盖无字幕视频)。

输出:
    默认只在终端打印正文，不落盘。需要存档时加 --save，才生成 <BVID>.transcript.txt。

注意:
    B 站字幕现在需要登录才能拿。脚本只读你自己的浏览器 cookie，不外传、不落盘分享。
    弹幕无需登录即可抓取，作为无字幕时的退路。
"""

import argparse
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request


def run_yt_dlp(args):
    cmd = [sys.executable, "-m", "yt_dlp"] + args
    return subprocess.run(cmd, capture_output=True, text=True)


def resolve_bvid(text):
    m = re.search(r"BV[0-9A-Za-z]{10}", text)
    return m.group(0) if m else text


def fetch_subtitle(url, browser):
    """抓 AI 字幕，返回带时间戳的文本(每行 "[mm:ss] 内容")；无则 None。"""
    out = tempfile.mkdtemp()
    args = [
        "--write-subs",          # B站 AI 字幕(ai-zh) 挂在普通字幕区，必须用 --write-subs 才能抓到
        "--write-auto-subs",     # 兼容 YouTube 等自动字幕区
        "--sub-langs",
        "ai-zh",
        "--skip-download",
        "-o",
        os.path.join(out, "%(id)s.%(ext)s"),
    ]
    if browser:
        args += ["--cookies-from-browser", browser]
    args.append(url)
    run_yt_dlp(args)
    for ext in ("ai-zh.json3", "ai-zh.vtt", "ai-zh.srt", "zh-CN.json3", "zh-CN.vtt", "zh-CN.srt", "json3", "vtt", "srt"):
        found = glob.glob(os.path.join(out, f"*.{ext}"))
        if found:
            return parse_subtitle_timed(found[0])
    return None


def list_subtitle_langs(url, browser):
    """探查真实字幕轨道，区分"视频无字幕"与"未登录/登录态失效"。

    返回 (langs, cookies_ok):
      - langs: 非 danmaku 的字幕语言代码列表(如 ['ai-zh'])，空列表表示视频仅挂了弹幕。
      - cookies_ok: 是否成功从浏览器读取到 cookie(用于判断是否真未登录)。
    """
    args = ["--list-subs", "--skip-download"]
    if browser:
        args += ["--cookies-from-browser", browser]
    args.append(url)
    res = run_yt_dlp(args)
    out = res.stdout + res.stderr
    cookies_ok = "Extracted" in out  # yt-dlp 成功提取 cookie 时打印 "Extracted N cookies from ..."
    langs = []
    capture = False
    for line in out.splitlines():
        if "Available subtitles" in line or "Available automatic captions" in line:
            capture = True
            continue
        if capture:
            stripped = line.strip()
            if not stripped or stripped.startswith("Language") or set(stripped) <= set("-"):
                continue
            first = stripped.split()[0] if stripped.split() else ""
            if first and first != "danmaku":
                langs.append(first)
    return langs, cookies_ok


def fetch_danmaku(url):
    """抓弹幕 XML，返回带时间戳的文本(每行 "[mm:ss] 内容")；无则 None。"""
    out = tempfile.mkdtemp()
    args = [
        "--write-subs",
        "--sub-langs",
        "danmaku",
        "--skip-download",
        "-o",
        os.path.join(out, "%(id)s.%(ext)s"),
        url,
    ]
    run_yt_dlp(args)
    found = glob.glob(os.path.join(out, "*.danmaku.xml"))
    if not found:
        return None
    return parse_danmaku(found[0])


def _fmt_ts(sec):
    sec = int(sec)
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def parse_subtitle_timed(path):
    """带时间戳解析字幕(每行 "[mm:ss] 内容")，给 AI 提供时间定位。"""
    if path.endswith(".json3"):
        data = json.load(open(path, encoding="utf-8"))
        lines = []
        for item in data.get("body", []):
            ts = _fmt_ts(item.get("from", 0))
            lines.append(f"[{ts}] {item.get('content', '').strip()}")
        return "\n".join(lines)
    if path.endswith(".vtt") or path.endswith(".srt"):
        raw = open(path, encoding="utf-8").read()
        blocks = re.split(r"\n\s*\n", raw)
        lines = []
        for block in blocks:
            blines = block.splitlines()
            tm = None
            for bl in blines:
                bl = bl.strip()
                m = re.search(r"(?:(\d+):)?(\d+):(\d+)[.,]\d+", bl)
                if m and "-->" in bl:
                    h = int(m.group(1)) if m.group(1) else 0
                    mm = int(m.group(2)); ss = int(m.group(3))
                    tm = _fmt_ts(h * 3600 + mm * 60 + ss)
            for bl in blines:
                bl = bl.strip()
                if not bl or bl.startswith(("WEBVTT", "NOTE")) or "-->" in bl or bl.isdigit():
                    continue
                lines.append(f"[{tm}] {bl}" if tm else bl)
        return "\n".join(lines)
    return ""


def parse_subtitle(path):
    """兼容旧接口: 不带时间戳平铺正文。"""
    return "\n".join(
        ln.split("] ", 1)[1] if ln.startswith("[") and "] " in ln else ln
        for ln in parse_subtitle_timed(path).splitlines()
    )


def parse_danmaku(path):
    """解析弹幕 XML，返回带时间戳文本(每行 "[mm:ss] 内容")。

    <d p="时间,类型,字号,颜色,时间戳,池,用户hash,弹幕id">内容</d>
    """
    data = open(path, encoding="utf-8", errors="ignore").read()
    items = re.findall(r'<d\s+p="([^"]*)">(.*?)</d>', data)
    rows = []
    for p, text in items:
        parts = p.split(",")
        try:
            ts = _fmt_ts(float(parts[0]))
        except (ValueError, IndexError):
            ts = "??:??"
        rows.append((ts, text))
    return "\n".join(f"[{ts}] {text}" for ts, text in rows)


def dedupe_danmaku(text, min_count=2):
    """弹幕提纯: 按(时间戳, 内容)去重并计数，高频项额外标注(xN)。

    默认保留全部弹幕(弹幕是百分百输出项，不做破坏性过滤)；min_count 仅用于
    把出现 >= min_count 的重复项折叠成带计数的一行，去重而不丢内容。
    返回 (clean_text, stats)。
    """
    counter = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        m = re.match(r"^(\[\d{1,2}:\d{2}(?::\d{2})?\])\s*(.*)$", line)
        if m:
            key = (m.group(1), m.group(2).strip())
        else:
            key = ("", line.strip())
        counter[key] = counter.get(key, 0) + 1
    total = sum(counter.values())
    lines = []
    repeated = 0
    for (ts, content), c in sorted(counter.items(), key=lambda x: (-x[1], x[0][0])):
        if c >= min_count:
            repeated += 1
            lines.append(f"{ts} {content}  (x{c})" if ts else f"{content}  (x{c})")
        else:
            lines.append(f"{ts} {content}" if ts else content)
    stats = f"弹幕提纯: 原始 {total} 条 -> 去重 {len(counter)} 种 (其中 {repeated} 种出现>= {min_count} 折叠计数，全部保留)"
    return "\n".join(lines), stats


def fetch_metadata(url, browser):
    """抓取视频元数据(标题/UP主/简介/分区/时长/发布时间)，无需登录。

    优先走 yt-dlp --dump-json(公开信息)；失败则退回网页解析关键字段。
    """
    args = ["--dump-json", "--skip-download"]
    if browser:
        args += ["--cookies-from-browser", browser]
    args.append(url)
    res = run_yt_dlp(args)
    meta = {}
    try:
        info = json.loads((res.stdout or "").strip().splitlines()[-1]) if res.stdout.strip() else {}
    except Exception:
        info = {}
    if info:
        meta = {
            "title": info.get("title", ""),
            "uploader": info.get("uploader", ""),
            "uploader_id": info.get("uploader_id", ""),
            "duration": info.get("duration", 0),
            "description": (info.get("description") or "").strip(),
            "categories": info.get("categories") or [],
            "tags": info.get("tags") or [],
            "view_count": info.get("view_count", 0),
            "danmaku_count": info.get("comment_count", 0),  # yt-dlp 未单独给弹幕数，留 0 表示未取
            "upload_date": info.get("upload_date", ""),
            "webpage_url": info.get("webpage_url", url),
        }
        return meta

    # 退回: 网页里抽标题 + 基础字段
    html = _http_get(url)
    m_title = re.search(r'"title":"([^"]+)"', html)
    meta["title"] = m_title.group(1) if m_title else ""
    meta["uploader"] = ""
    meta["duration"] = 0
    meta["description"] = ""
    meta["categories"] = []
    meta["tags"] = []
    meta["view_count"] = 0
    meta["danmaku_count"] = 0
    meta["upload_date"] = ""
    meta["webpage_url"] = url
    return meta


def search_bili(keyword, cookies=None, limit=20, order="totalrank"):
    """关键字搜视频(先 API，空了回退网页搜索页解析)。返回 [(bvid, title, author, duration), ...]。

    order: totalrank(默认综合) / click(播放) / pubdate(最新) / dm(弹幕) / stow(收藏)。
    注: API 接口 `x/web-interface/(wbi/)search/all/v2` 现常被风控返回空壳(numResults>0 但 result 空)，
        此时自动改抓 https://search.bilibili.com 网页端 SSR 数据(同样可拿标题/BV/UP/时长)。
    """
    cookie_header = {"Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items())} if cookies else None
    results = []
    try:
        img_key, sub_key = get_wbi_keys(cookies)
        if img_key and sub_key:
            params = wbi_sign({"keyword": keyword, "order": order, "page": 1}, img_key, sub_key)
            url = "https://api.bilibili.com/x/web-interface/wbi/search/all/v2?" + urllib.parse.urlencode(params)
        else:
            enc = urllib.parse.quote(keyword)
            url = f"https://api.bilibili.com/x/web-interface/search/all/v2?keyword={enc}&order={order}"
        raw = _http_get(url, headers=cookie_header)
        data = json.loads(raw)
        for group in data.get("data", {}).get("result", []):
            if group.get("result_type") != "video":
                continue
            for item in group.get("result", []):
                bvid = item.get("bvid", "")
                if not bvid:
                    continue
                title = re.sub(r"<[^>]+>", "", item.get("title", "")).strip()
                results.append((bvid, title, item.get("author", ""), item.get("duration", "")))
                if len(results) >= limit:
                    return results
    except Exception:
        pass

    # API 空壳/失败 → 回退网页搜索页(SSR 直接渲染卡片，躲开 API 风控)
    if not results:
        try:
            html = _http_get(
                "https://search.bilibili.com/all?keyword=" + urllib.parse.quote(keyword) + f"&order={order}",
                headers=cookie_header,
            )
            for card in re.split(r'<div class="bili-video-card__wrap"', html)[1:]:
                m_bv = re.search(r"/video/(BV[0-9A-Za-z]{10})", card)
                m_tit = re.search(r'bili-video-card__info--tit" title="([^"]+)"', card)
                m_author = re.search(r'bili-video-card__info--author"[^>]*>([^<]+)<', card)
                m_dur = re.search(r'bili-video-card__stats__duration"[^>]*>([^<]+)<', card)
                if m_bv and m_tit:
                    results.append((m_bv.group(1), m_tit.group(1), m_author.group(1) if m_author else "", m_dur.group(1) if m_dur else ""))
                    if len(results) >= limit:
                        return results
        except Exception:
            pass
    return results


def _http_get(url, headers=None, data=None):
    base = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.bilibili.com",
        "Origin": "https://www.bilibili.com",
    }
    base.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=base)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="replace")


def load_cookies_from_file(path):
    cookies = {}
    for line in open(path, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            cookies[parts[5]] = parts[6]
    return cookies


def load_browser_cookies(browser):
    """用 yt-dlp 把浏览器登录态提取为 dict；失败(未装/DPAPI 加密/未登录)返回 None。"""
    if not browser:
        return None
    try:
        from yt_dlp.cookies import extract_cookies_from_browser
        jar = extract_cookies_from_browser(browser)
        cks = {}
        for c in jar:
            if c.domain and "bilibili" in c.domain and c.name and c.value:
                cks[c.name] = c.value
        return cks or None
    except Exception:
        return None


def wbi_sign(params, img_key, sub_key):
    # B 站 wbi 签名：mixinKey = (img_key+sub_key)[46位乱序表]，再对参数按 key 排序加 wts
    mixin = img_key + sub_key
    order = [46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
             33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
             61, 26, 17, 11, 52, 34, 44, 25, 57, 60, 59, 22, 6, 63, 1, 4, 30, 51, 62,
             21, 0, 54, 36, 20, 56, 32]
    key = "".join(mixin[i] for i in order)[:32]
    params = dict(params)
    params["wts"] = int(time.time())
    items = sorted(params.items())
    query = urllib.parse.urlencode(items)
    query += key
    params["w_rid"] = hashlib.md5(query.encode("utf-8")).hexdigest()
    return params


def fetch_subtitle_via_api(bvid, cookies):
    # 1. 拿 wbi 的 img_key/sub_key
    nav = json.loads(_http_get(
        "https://api.bilibili.com/x/web-interface/nav",
        headers={"Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items())},
    ))
    wbi = nav.get("data", {}).get("wbi_img", {})
    img_key = wbi.get("img_url", "").rsplit("/", 1)[-1].split(".")[0]
    sub_key = wbi.get("sub_url", "").rsplit("/", 1)[-1].split(".")[0]
    if not img_key or not sub_key:
        return None

    # 2. 拿 aid + cid（从网页里抽）
    html = _http_get(f"https://www.bilibili.com/video/{bvid}",
                     headers={"Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items())})
    m_aid = re.search(r'"aid":(\d+)', html)
    m_cid = re.search(r'"cid":(\d+)', html)
    if not m_aid or not m_cid:
        return None
    aid, cid = m_aid.group(1), m_cid.group(1)

    # 3. 调 player/wbi/v2 拿字幕直链
    params = wbi_sign({"aid": aid, "cid": cid, "bvid": bvid}, img_key, sub_key)
    body = urllib.parse.urlencode(params).encode("utf-8")
    resp = json.loads(_http_get(
        "https://api.bilibili.com/x/player/wbi/v2",
        headers={"Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items()),
                 "Content-Type": "application/x-www-form-urlencoded"},
        data=body,
    ))
    subtitles = resp.get("data", {}).get("subtitle", {}).get("subtitles", [])
    if not subtitles:
        return None
    # 优先 AI 字幕（ai_type>0），否则取第一个
    sub = next((s for s in subtitles if s.get("ai_type", 0) > 0), subtitles[0])
    sub_url = sub["subtitle_url"]
    if sub_url.startswith("//"):
        sub_url = "https:" + sub_url
    raw = _http_get(sub_url)
    data = json.loads(raw)
    return "\n".join(item.get("content", "") for item in data.get("body", []))


def get_wbi_keys(cookies=None):
    cookie_header = {"Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items())} if cookies else {}
    nav = json.loads(_http_get("https://api.bilibili.com/x/web-interface/nav", headers=cookie_header))
    wbi = nav.get("data", {}).get("wbi_img", {})
    img_key = wbi.get("img_url", "").rsplit("/", 1)[-1].split(".")[0]
    sub_key = wbi.get("sub_url", "").rsplit("/", 1)[-1].split(".")[0]
    return img_key, sub_key


def fetch_aid(bvid, img_key, sub_key):
    params = wbi_sign({"bvid": bvid}, img_key, sub_key)
    url = "https://api.bilibili.com/x/web-interface/view?" + urllib.parse.urlencode(params)
    view = json.loads(_http_get(url))
    if view.get("code") != 0:
        return None
    return view.get("data", {}).get("aid")


def fetch_comments(bvid, cookies=None, max_pages=10, mode=2):
    """拉取评论(无需登录，公开数据)。mode=2 按热度，mode=3 按时间。"""
    try:
        img_key, sub_key = get_wbi_keys(cookies)
    except Exception as e:
        print(f"[!] 拿 wbi 密钥失败: {e}")
        return None
    if not img_key or not sub_key:
        return None
    aid = fetch_aid(bvid, img_key, sub_key)
    if not aid:
        return None
    comments = []
    next_cursor = 0
    for _ in range(max_pages):
        params = wbi_sign(
            {"oid": aid, "type": "1", "mode": str(mode), "next": str(next_cursor)},
            img_key, sub_key,
        )
        url = "https://api.bilibili.com/x/v2/reply/wbi/main?" + urllib.parse.urlencode(params)
        try:
            resp = json.loads(_http_get(url))
        except Exception as e:
            print(f"[!] 评论请求失败: {e}")
            break
        if resp.get("code") != 0:
            print(f"[!] 评论接口返回 code={resp.get('code')}")
            break
        d = resp.get("data", {})
        for r in (d.get("replies") or []):
            msg = (r.get("content") or {}).get("message", "")
            if msg:
                comments.append(msg)
            for sub in (r.get("replies") or []):
                sub_msg = (sub.get("content") or {}).get("message", "")
                if sub_msg:
                    comments.append("    ↳ " + sub_msg)
        cursor = d.get("cursor", {})
        if cursor.get("is_end"):
            break
        nxt = cursor.get("next", 0)
        if not nxt or nxt == next_cursor:
            break
        next_cursor = nxt
    return comments


def main():
    parser = argparse.ArgumentParser(description="把 B 站视频转成可阅读文本")
    parser.add_argument("target", help="BVID / 视频链接 / 搜索关键词(配合 --search)")
    parser.add_argument("--browser", default="firefox", help="用来读登录态的浏览器，默认 firefox(Chrome/Edge 因 DPAPI 加密易失败)")
    parser.add_argument("--cookies", default=None, help="Netscape 格式 cookie 文件路径(导出的 bilibili cookie，绕过浏览器加密)")
    parser.add_argument("--save", action="store_true", help="落盘保存为 <BVID>.transcript.txt(默认只打印到终端，不保存)")
    parser.add_argument("--asr", action="store_true", help="同时尝试音频转写(需 ffmpeg+whisper，纯预留)")
    parser.add_argument("--preview", type=int, default=40, help="弹幕预览行数")
    parser.add_argument("--comments", action="store_true", help="额外拉取评论(公开数据，无需登录)")
    parser.add_argument("--comment-pages", type=int, default=10, help="评论翻页上限(每页约20条)")
    parser.add_argument("--comment-mode", type=int, default=2, help="评论排序: 2=按热度, 3=按时间")
    parser.add_argument("--search", action="store_true", help="把 target 当关键词搜索视频，列出候选 BV")
    parser.add_argument("--search-limit", type=int, default=20, help="搜索结果数量上限(默认20)")
    parser.add_argument("--search-order", default="totalrank", help="搜索排序: totalrank(综合)/click(播放)/pubdate(最新)/dm(弹幕)/stow(收藏)")
    parser.add_argument("--min-danmaku", type=int, default=2, help="弹幕折叠阈值: 出现 >= 该值的重复项折叠成带(xN)的一行(默认2，全部保留不删除)")
    parser.add_argument("--no-danmaku", action="store_true", help="只取字幕，不抓弹幕")
    args = parser.parse_args()

    # 搜索模式: 列出候选视频，不抓正文
    if args.search:
        print(f"[*] 搜索: {args.target}")
        cookies = None
        if args.cookies and os.path.exists(args.cookies):
            cookies = load_cookies_from_file(args.cookies)
        else:
            cookies = load_browser_cookies(args.browser)
        results = search_bili(args.target, cookies=cookies, limit=args.search_limit, order=args.search_order)
        if not results:
            print("[X] 没搜到结果(接口可能被限流或需登录)")
            sys.exit(1)
        print(f"[+] 搜到 {len(results)} 条(取前 {args.search_limit}):")
        for i, (bvid, title, author, dur) in enumerate(results, 1):
            print(f"   {i:2d}. {bvid}  [{dur}]  {title}  UP:{author}")
        return

    url = args.target if args.target.startswith("http") else f"https://www.bilibili.com/video/{args.target}"
    bvid = resolve_bvid(args.target)
    print(f"[*] 处理: {bvid}")

    # --- 1. 元数据(标题/UP/简介/分区/时长)，置顶给 AI 看背景 ---
    meta = fetch_metadata(url, args.browser)
    print("=" * 56)
    print(f"标题 : {meta.get('title', '')}")
    print(f"UP主 : {meta.get('uploader', '')} ({meta.get('uploader_id', '')})")
    dur = meta.get("duration", 0) or 0
    print(f"时长 : {_fmt_ts(dur)}   播放: {meta.get('view_count', 0)}")
    if meta.get("categories"):
        print(f"分区 : {', '.join(meta.get('categories', []))}")
    if meta.get("tags"):
        print(f"标签 : {', '.join(meta.get('tags', [])[:12])}")
    if meta.get("upload_date"):
        print(f"发布 : {meta.get('upload_date')}")
    if meta.get("description"):
        desc = meta["description"]
        if len(desc) > 240:
            desc = desc[:240] + " …(截断)"
        print(f"简介 : {desc}")
    print("=" * 56)

    # --- 2. 字幕(优先，带时间戳) ---
    subtitle_text = ""
    sub_source = ""
    # 优先走 API 直连(用导出的 cookie 文件)
    if args.cookies and os.path.exists(args.cookies):
        print("[*] 使用 cookie 文件走 API 直连拿字幕")
        try:
            cookies = load_cookies_from_file(args.cookies)
            api_text = fetch_subtitle_via_api(bvid, cookies)
            if api_text and api_text.strip():
                subtitle_text = api_text
                sub_source = "AI 字幕(API 直连，带时间戳)"
        except Exception as e:
            print(f"[!] API 直连失败: {e}")

    # API 没拿到再退回 yt-dlp
    if not subtitle_text.strip():
        sub_langs, cookies_ok = list_subtitle_langs(url, args.browser)
        if sub_langs:
            if not cookies_ok:
                print("[!] 检测到字幕轨道但 cookie 未读取成功(可能未登录 / 浏览器未装 / DPAPI 加密)。")
                print("    → 换 firefox 登录态，或导出 cookie 文件用 --cookies 喂入。")
            sub_path = fetch_subtitle(url, args.browser)
            if sub_path:
                subtitle_text = sub_path  # 已是带时间戳文本
                sub_source = "AI 字幕(yt-dlp，带时间戳)"
            elif not cookies_ok:
                print("[!] 有字幕轨道但始终未下载成功 -> 跳过字幕(弹幕仍会抓取)。")
        else:
            if cookies_ok:
                print("[*] 已读取登录态，该视频未挂字幕轨道(无字幕)。")
            else:
                print("[!] 未读取到浏览器 cookie 且未能确认字幕轨道 -> 跳过字幕(弹幕仍会抓取)。")

    if subtitle_text.strip():
        print(f"[+] 字幕来源: {sub_source}  (共 {len(subtitle_text.splitlines())} 行)")

    # --- 3. 弹幕(百分百保留，带时间戳 + 提纯) ---
    danmaku_text = ""
    if not args.no_danmaku:
        dm_text = fetch_danmaku(url)  # 已带时间戳
        if dm_text:
            clean, stats = dedupe_danmaku(dm_text, min_count=args.min_danmaku)
            print(f"[+] 弹幕: {stats}")
            danmaku_text = clean
        else:
            print("[!] 弹幕未抓到(接口异常或视频无弹幕)")

    # ASR 预留
    if args.asr:
        print("[*] ASR 模式需要你本机安装 ffmpeg 与 openai-whisper，并把音频转写结果粘回来")

    # --- 4. 组装正文预览 ---
    print("\n" + "-" * 56)
    if subtitle_text.strip():
        print(f"[字幕] 前 {args.preview} 行:")
        for line in subtitle_text.splitlines()[: args.preview]:
            print("   ", line)
    else:
        print("[字幕] (无)")

    if danmaku_text.strip():
        print(f"\n[弹幕·提纯] 前 {args.preview} 行:")
        for line in danmaku_text.splitlines()[: args.preview]:
            print("   ", line)
    else:
        print("[弹幕] (无)")
    print("-" * 56)

    # --- 5. 落盘(字幕 + 弹幕 + 元数据) ---
    if args.save:
        out_path = os.path.join(os.getcwd(), f"{bvid}.transcript.txt")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(f"# {bvid} 内容文本\n")
            f.write(f"标题: {meta.get('title', '')}\n")
            f.write(f"UP主: {meta.get('uploader', '')}\n")
            f.write(f"时长: {_fmt_ts(dur)}  发布: {meta.get('upload_date', '')}\n")
            if meta.get("description"):
                f.write(f"简介: {meta.get('description')}\n")
            f.write(f"\n## 字幕 ({sub_source or '无'})\n\n")
            f.write(subtitle_text if subtitle_text.strip() else "(无字幕)\n")
            f.write(f"\n\n## 弹幕 (提纯阈值>={args.min_danmaku})\n\n")
            f.write(danmaku_text if danmaku_text.strip() else "(无弹幕)\n")
        print(f"[+] 已写入: {out_path}")

    # --- 6. 评论(公开数据，无需登录) ---
    if args.comments:
        print("[*] 拉取评论中...")
        comments = fetch_comments(bvid, cookies=None, max_pages=args.comment_pages, mode=args.comment_mode)
        if comments:
            print(f"[+] 评论(共 {len(comments)} 条，来源: 公开评论接口):")
            for c in comments:
                print("   ", c)
            if args.save:
                with open(out_path, "a", encoding="utf-8") as f:
                    f.write(f"\n\n## 评论(共 {len(comments)} 条，排序模式 {args.comment_mode})\n\n")
                    f.write("\n".join(comments))
                print(f"[+] 评论已追加到: {out_path}")
        else:
            print("[!] 没拿到评论")


if __name__ == "__main__":
    main()
