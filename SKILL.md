---
name: bili-watch
description: "将 B站（Bilibili）视频转成可阅读文本，让 AI 看懂视频内容并总结、问答。优先抓 AI 字幕（需用户浏览器登录态）；无论有无字幕，都百分百输出带时间戳的弹幕（无需登录，可折叠重复）。Triggers: 用户分享 B站视频链接或 BV 号想总结或转写或讨论内容时，如「看这个视频」「这个B站视频讲啥」「帮我看看B站」「B站视频转文字」「bilibili 字幕 弹幕」。"
version: 1.2.1
author: WorkBuddy
tags:
  - bilibili
  - video
  - transcription
  - multimodal
license: MIT
agent_created: true
---

# Bili Watch

## Overview
让 WorkBuddy 读懂 B站视频，两条路径：
1. **文本路径**：抓字幕（ai-zh）/弹幕，由 AI 阅读总结（`bili_watch.py`）——能"听"台词，但看不到画面。
2. **画面路径**：下载视频 + ffmpeg 抽关键帧 + AI 逐张读图（`bili_frames.py`）——真实看到画面（运镜/UI/动作/贴图），是陪看、画面型整活（PVZ 鬼畜、MC 实拍、游戏集锦）的唯一靠谱方式。

**边界**：本 skill 只做"视频→文本"的单向转写，**不**涉及自动刷推荐/投币/评论/私信等账号托管行为（那类高风险工具见开源项目 `bilibili_learning_bot`，与本 skill 无关且默认不推荐）。

## Key Constraints (from real probing)
- **字幕锁登录**：B站字幕（含 AI 字幕）现已要求登录，无 cookie 时报 `Subtitles are only available when logged in`。AI 字幕的语言代码通常是 `ai-zh`（不是 `zh-CN`），`--list-subs` 里显示为 `ai-zh srt` / `zh-CN.json3` 才是真字幕轨道。
- **浏览器选择（关键）**：
  - **优先用 Firefox**：`--cookies-from-browser firefox` 能稳定拿到登录态 AI 字幕（Firefox cookie 无系统级加密，yt-dlp 直接读）。实测 `--list-subs` 成功列出 `ai-zh`，字幕抓得到。
  - **Edge/Chrome 有 App-Bound Encryption（DPAPI）加密**：`--cookies-from-browser edge` 会报 `Failed to decrypt with DPAPI`，yt-dlp 读不出 cookie，字幕分支退化成弹幕。
  - **导出的 cookie 文件不可靠**：用 Cookie-Editor 导出 Netscape 格式 `.txt` 再 `--cookies 文件` 喂 `api.bilibili.com`，实测 `nav` 接口返回 `isLogin=false`（SESSDATA 在服务端已失效/被轮换，导出的是过期凭证），导致 `player/wbi/v2` 不返回字幕，只能退弹幕。**不要依赖导出的 cookie 文件**，改用 Firefox 实时登录态。
- **弹幕无需登录**：`yt-dlp --write-subs --sub-langs danmaku --skip-download` 可直接抓弹幕 XML，作为无字幕时的退路（内容碎片化，且弹幕可能和当前视频主题混流，仅作大意参考，不可当真实字幕）。
- **反爬**：默认 UA 直连 bilibili.com 会被 412 拦截；抓首页 BV 号/调接口需带浏览器 UA + Referer/Origin（如 `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36`，Referer `https://www.bilibili.com`）。
- **环境依赖**：沙箱/新机常缺 `yt-dlp`，先 `python -m pip install -q yt-dlp`。抽帧需要 ffmpeg：`pip install imageio-ffmpeg`（自带静态二进制，无需系统装 ffmpeg）。whisper 通常缺失（ASR 音频转写分支默认不启用，用户已确认不需要）。

## Workflow
1. 确认目标是 B站视频（链接或 BV 号）。
2. 优先走字幕：运行 `scripts/bili_watch.py <BVID> --cookies-from-browser firefox`（脚本内部用 yt-dlp 抓并解析字幕）。**需在用户本机 Windows（Firefox 已登录 B站）运行**才拿得到字幕。
3. 先用 `--list-subs` 确认轨道：`python -m yt_dlp --cookies-from-browser firefox --list-subs <URL>`，看到 `ai-zh` 再抓；若只有 `danmaku` 说明登录态没过或视频无字幕。
4. 若无字幕/未登录，脚本自动退弹幕分支，输出弹幕转写（碎片化大意，且可能与视频主题不符）。沙箱内无登录态时只能走这条。
5. 拿到文本后，由 AI 阅读并总结/问答。
6. **画面型视频**（无字幕、或信息在画面里：整活/鬼畜/实拍/游戏集锦）：`python scripts/bili_frames.py <BVID>` 下载并抽帧，AI 用 Read 逐张读图（**每批 ≤4 张**，一次并发太多会报"模型不支持图片"）。**严禁拿标题/标签/套路脑补画面冒充"看见"**；看不清就 `--width 1920` 放大重抽。
7. **不要落盘**：默认只在终端打印预览，不写文件。需长期存档才加 `--save` 生成 `<BVID>.transcript.txt`（用户曾明确要求不要默认保存弹幕文件）。

## Bundled Script
`scripts/bili_watch.py` — 把 B站视频转成文本（字幕+弹幕）。
- 用法：`python bili_watch.py <BVID 或链接/关键词> [--browser firefox] [--cookies 文件] [--save] [--search]`
- `--browser`：读哪个浏览器的 B站登录态（**默认 firefox**；edge/chrome 因 DPAPI 加密会失败，已设为非默认）。
- `--cookies`：Netscape 格式 cookie 文件（已加 API 直连分支：调 `player/wbi/v2` 拿 AI 字幕直链）。**注意**：导出的 cookie 文件常因 SESSDATA 失效被判未登录，优先用 `--cookies-from-browser firefox`。
- `--save`：落盘保存为 `<BVID>.transcript.txt`（**默认不保存**，仅终端预览）。文件含元数据+字幕+弹幕+评论。
- `--comments`：额外拉取公开评论（走 `x/v2/reply/wbi/main`，**无需登录**，复用脚本内 `wbi_sign` 签名）；`--comment-pages` 翻页上限（默认10，每页约20条）、`--comment-mode` 2=按热度/3=按时间。子回复以 `↳ ` 前缀缩进。`--save` 时评论会一并追加到文件。
- `--search`：把 target 当**关键词搜索视频**，列出候选 BV。`--search-limit` 数量（默认20）、`--search-order` totalrank/click/pubdate/dm/stow。**2026-08-25 已修**：先走 wbi 签名接口 `x/web-interface/wbi/search/all/v2`（自动带浏览器登录态或 `--cookies`），API 常被风控返回空壳（`numResults>0` 但 result 空）时自动回退抓 `https://search.bilibili.com/all` 网页端 SSR 卡片数据（解析 `bili-video-card__wrap` 块拿标题/BV/UP/时长）。搜索关键词请给完整上下文（如"NX树 指令 我的世界"），分词过细容易命中无关内容。
- `--min-danmaku`：弹幕折叠阈值（默认2）。出现 >= 该值的重复弹幕折叠成带 `(xN)` 的一行；**全部弹幕都保留，不做破坏性删除**（弹幕是百分百输出项，不再是退路）。
- `--no-danmaku`：只取字幕、不抓弹幕。
- **输出结构（升级后）**：①元数据置顶（标题/UP主/时长/播放/分区/标签/发布/简介，给 AI 先看背景）；②字幕优先、带时间戳 `[mm:ss]`；③弹幕百分百保留、带时间戳 + 去重折叠；④评论（可选）。字幕与弹幕解耦：有字幕也给弹幕，无字幕则弹幕独立输出。
- 解析逻辑：json3/vtt/srt 字幕按 `from`/时间码提取并附 `[时间戳]`；弹幕 XML 按 `<d p="时间,...">` 取时间点附 `[时间戳]`；评论取 `data.replies[].content.message`（含 `replies` 子回复）。
- 无字幕视频：B 站侧只挂了弹幕、没挂字幕的视频（如本会话 BV1eVgA64EpH、BV1cj8c6jE7f），`--list-subs` 只见 `danmaku`；这类视频弹幕独立百分百输出，不再被当"退路"误报。
- **状态区分（已修复误报）**：脚本现用 `--list-subs` 先探查真实轨道，不把"无字幕"误判成"未登录"。三种分支：①已读取登录态且视频确实无字幕轨道 → 提示"该视频未挂字幕轨道(无字幕)"；②有字幕轨道但 cookie 未读取成功（未登录/DPAPI加密/浏览器未装）→ 提示去换 firefox 或喂 `--cookies`；③既无 cookie 也未能确认轨道 → 提示跳过字幕（弹幕仍抓）。旧版统一打"可能未登录或该视频无字幕"已废弃。

`scripts/bili_frames.py` — 下载 B站视频 + ffmpeg 抽帧，供 AI 读图看画面（v1.2.0 新增）。
- 用法：`python bili_frames.py <BVID> [--interval 3] [--width 1280] [--outdir 目录]`；或 `--video <本地.mp4>` 跳过下载直接抽帧。
- 依赖：`pip install yt-dlp imageio-ffmpeg`（imageio-ffmpeg 自带静态 ffmpeg，无需系统装）。
- **自动选格式（关键坑）**：`-f "bv*[height<=1080]+ba/b[height<=1080]" --format-sort "vbr:asc"` —— 强制挑 1080p 内码率最低的普通档，避开大会员「1080P 高码率/60帧」档（free 账号下会报格式不可用）。格式 ID 因视频而异（30080/100050/80…），**禁止硬编码格式 ID**。失败自动降级 720p 重试。
- 读图规范：AI 用 Read 逐张读帧，**每批 ≤4 张**；**严禁脑补画面冒充看见**（历史翻车：拿标题猜"治愈向混剪"结果实为聊天体整活）；看不清放大 `--width 1920` 重抽。
- **合集/特殊页坑**：遇到 `Unable to extract initial state` 报错（常见于系列合集页或"纯享版"合集），给 yt-dlp 加 `--extractor-args "bilibili:download_via_api=true"` 改走 view API 提取；若该 BV 实际是合集，默认会下全部分P，必须追加 `--playlist-items N` 只取第 N 个分P，否则可能一次性下几百个视频。
- **超长视频抽帧坑**：`fps=1/interval` 滤镜会完整软解整个视频，对数小时以上的"纯享版"循环视频会卡死。此时应改用 `ffmpeg -ss 时间点 -i <视频> -frames:v 1` 按时间点 seek 抽代表性单帧（每 10~30 分钟抽一张），而不是用 `fps` 连续抽帧。

## Notes
- 协作方式：用户在自己的 Windows 上跑脚本拿文本后，把结果贴给 WorkBuddy；或若 WorkBuddy 能访问本机则直接调用脚本。沙箱环境无浏览器登录态，字幕分支演示不了，但弹幕分支可在此直接验证。
- 与 bilibili_learning_bot 区分：那是全账号托管（刷推荐/投币/评论/私信），封号 + API 费风险高；本 skill 仅做内容转写，低风险。
