#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bili_frames.py — 下载 B站视频并按间隔抽帧，供 AI 逐张读图"看画面"。

为什么需要它：bili_watch.py 的字幕/弹幕只能"听"到台词，画面信息（运镜、
贴图、UI、动作、无字幕的整活）拿不到。本脚本把
  下载(自动选 1080p 普通档，避开大会员高码率) + ffmpeg 抽帧
一条龙做完，输出一个帧目录；AI 用 Read 工具逐张读图，即真实看到画面。

用法:
  python bili_frames.py <BV号或链接> [--interval 3] [--width 1280] [--outdir 目录]
  python bili_frames.py --video <本地.mp4> [--interval 3] [--width 1280]

依赖:
  pip install yt-dlp imageio-ffmpeg     # imageio-ffmpeg 提供静态 ffmpeg 二进制

读图注意事项（给 AI）:
  - 用 Read 工具逐张读，每批 <= 4 张；一次并发读太多会触发"模型不支持图片"。
  - 不要拿标题/标签/套路脑补画面内容冒充"看见"；看不清就放大重抽(--width 1920)。
"""
import argparse
import os
import re
import shutil
import subprocess
import sys


def get_ffmpeg():
    """优先 imageio-ffmpeg 的静态二进制，回退系统 ffmpeg。"""
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except ImportError:
        pass
    p = shutil.which("ffmpeg")
    if p:
        return p
    print("[!] 未找到 ffmpeg。请先安装: pip install imageio-ffmpeg", file=sys.stderr)
    sys.exit(1)


def download(bv, ff, outdir, use_cookies=True):
    """yt-dlp 下载并合并 mp4。

    -f "bv*[height<=1080]+ba/b[height<=1080]"  + format_sort "vbr:asc":
    强制在 1080p 以内挑「码率最低」的视频流，避开大会员「1080P 高码率/
    60帧」档（那种档 free 账号会报格式不可用）。这是实测踩坑后选定的
    通用策略：不同视频的可用格式 ID 不固定（30080/100050/80…），
    不能硬编码格式 ID。
    """
    import yt_dlp

    out = os.path.join(outdir, f"watch_{bv}.%(ext)s")
    ydl_opts = {
        "quiet": False,
        "ffmpeg_location": ff,
        "format": "bv*[height<=1080]+ba/b[height<=1080]",
        "format_sort": ["vbr:asc"],
        "merge_output_format": "mp4",
        "outtmpl": out,
    }
    if use_cookies:
        ydl_opts["cookiesfrombrowser"] = ("firefox",)
    url = f"https://www.bilibili.com/video/{bv}"
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    mp4 = os.path.join(outdir, f"watch_{bv}.mp4")
    if not os.path.exists(mp4):
        print(f"[!] 合并后文件不存在: {mp4}", file=sys.stderr)
        sys.exit(1)
    return mp4


def extract_frames(video, ff, interval, width, outdir):
    os.makedirs(outdir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(video))[0]
    pattern = os.path.join(outdir, f"{stem}_%03d.jpg")
    vf = f"fps=1/{interval},scale={width}:-1"
    cmd = [ff, "-hide_banner", "-loglevel", "error", "-i", video, "-vf", vf, "-q:v", "3", pattern]
    print("[*] 抽帧:", " ".join(cmd))
    r = subprocess.run(cmd)
    if r.returncode != 0:
        print("[!] 抽帧失败", file=sys.stderr)
        sys.exit(1)
    frames = sorted(f for f in os.listdir(outdir) if f.endswith(".jpg"))
    print(f"[+] 完成: {len(frames)} 帧 -> {outdir}")
    for f in frames:
        print("   ", os.path.join(outdir, f))
    return frames


def main():
    ap = argparse.ArgumentParser(description="B站视频下载+抽帧，供 AI 读图看画面")
    ap.add_argument("target", nargs="?", help="BV 号或 B站链接")
    ap.add_argument("--video", help="本地视频文件，跳过下载直接抽帧")
    ap.add_argument("--interval", type=float, default=3, help="抽帧间隔秒数（默认3）")
    ap.add_argument("--width", type=int, default=1280, help="帧宽度（默认1280，看不清可加大）")
    ap.add_argument("--outdir", default="frames", help="输出目录（默认 frames/）")
    ap.add_argument("--no-cookies", action="store_true", help="不读 Firefox 登录态（可能只能下低清晰度）")
    args = ap.parse_args()

    ff = get_ffmpeg()

    if args.video:
        extract_frames(args.video, ff, args.interval, args.width, args.outdir)
        return

    if not args.target:
        ap.error("需要 BV 号/链接，或 --video 指定本地文件")
    m = re.search(r"(BV[0-9A-Za-z]{10})", args.target)
    if not m:
        ap.error(f"无法识别 BV 号: {args.target}")
    bv = m.group(1)
    os.makedirs(args.outdir, exist_ok=True)
    print(f"[*] {bv} 下载+抽帧（间隔{args.interval}s 宽{args.width}）")
    try:
        mp4 = download(bv, ff, args.outdir, use_cookies=not args.no_cookies)
    except Exception as e:
        print(f"[!] 1080p 档下载失败({e})，降级 720p 重试…", file=sys.stderr)
        mp4 = download_retry_720(bv, ff, args.outdir, use_cookies=not args.no_cookies)
    extract_frames(mp4, ff, args.interval, args.width, args.outdir)


def download_retry_720(bv, ff, outdir, use_cookies=True):
    """降级策略：1080p 全不可用时退 720p。"""
    import yt_dlp

    out = os.path.join(outdir, f"watch_{bv}.%(ext)s")
    ydl_opts = {
        "quiet": False,
        "ffmpeg_location": ff,
        "format": "bv*[height<=720]+ba/b[height<=720]",
        "format_sort": ["vbr:asc"],
        "merge_output_format": "mp4",
        "outtmpl": out,
    }
    if use_cookies:
        ydl_opts["cookiesfrombrowser"] = ("firefox",)
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([f"https://www.bilibili.com/video/{bv}"])
    mp4 = os.path.join(outdir, f"watch_{bv}.mp4")
    if not os.path.exists(mp4):
        print(f"[!] 720p 降级也失败: {mp4}", file=sys.stderr)
        sys.exit(1)
    return mp4


if __name__ == "__main__":
    main()
