# bili-watch

把 B站（Bilibili）视频转成可阅读文本，让 AI 能读懂视频内容并总结、问答、生成文档。支持两条路径：

1. **文本路径**：抓字幕（ai-zh）/弹幕/评论，由 AI 阅读总结（`bili_watch.py`）——能"听"台词，但看不到画面。
2. **画面路径**：下载视频 + ffmpeg 抽关键帧 + AI 逐张读图（`bili_frames.py`）——真实看到画面（运镜/UI/动作/贴图），是陪看、画面型整活（PVZ 鬼畜、MC 实拍、游戏集锦）的唯一靠谱方式。

## 能拉什么

| 数据 | 说明 | 是否需登录 |
|---|---|---|
| AI 字幕 | 优先抓取，带 `[mm:ss]` 时间戳 | 需要（Firefox 登录态） |
| 弹幕 | **百分百输出**，带时间戳、可折叠重复 | 不需要 |
| 评论 | 公开评论，含子回复 | 不需要 |
| 元数据 | 标题 / UP主 / 时长 / 播放 / 分区 / 标签 / 简介 | 不需要 |
| 画面帧 | 下载视频 + ffmpeg 抽关键帧，供 AI 逐张读图看画面 | 不需要（仅下载，无需登录态） |

## 用法

```bash
# 转写单个视频（默认 Firefox 登录态抓字幕，弹幕始终输出）
python bili_watch.py BV1cj8c6jE7f --comments

# 按关键词搜索视频（本机已登录或 --cookies 才能拿列表）
python bili_watch.py "Linux 修复 bug" --search --search-limit 10

# 落盘保存（默认不保存）
python bili_watch.py BV1cj8c6jE7f --save

# 画面路径：抽帧看画面（无字幕 / 画面型视频：整活、鬼畜、实拍、游戏集锦）
python scripts/bili_frames.py BV1cj8c6jE7f --interval 3 --width 1280
# 已有本地 mp4 也可跳过下载直接抽帧
python scripts/bili_frames.py --video "本地视频.mp4" --interval 2
```

参数（bili_watch.py）：

- `--browser firefox`：读哪个浏览器登录态（默认 firefox；Chrome/Edge 因 DPAPI 加密会失败）
- `--cookies 文件`：Netscape 格式 cookie 文件（一般不推荐，SESSDATA 易失效）
- `--comments`：额外拉取公开评论；`--comment-pages` 翻页上限、`--comment-mode` 2=热度/3=时间
- `--search`：把 target 当关键词搜索；`--search-limit`、`--search-order`
- `--min-danmaku N`：弹幕折叠阈值，默认 2（出现 >= N 次折叠成 `xN`，全部保留）
- `--no-danmaku`：关闭弹幕输出
- `--save`：保存为 `<BVID>.transcript.txt`

参数（bili_frames.py 画面抽帧）：

- `--interval N`：抽帧间隔秒数，默认 3
- `--width N`：抽帧宽度（像素），默认 1280；看不清可设 1920 重抽
- `--outdir 目录`：帧输出目录，默认 `bili_frames/`
- `--video 本地.mp4`：跳过下载、直接对本地视频抽帧

## 关键提示

- **字幕锁登录**：B站字幕需登录，`--cookies-from-browser firefox` 最稳；Chrome/Edge 因 App-Bound Encryption 读不出 cookie。
- **弹幕是重点**：无论有无字幕，弹幕都输出（这是对「无字幕视频只看弹幕」的升级——弹幕不再是退路）。
- **无字幕 ≠ 未登录**：脚本会先 `--list-subs` 探查真实轨道，区分「视频本来没字幕」和「登录态没读到」，不再误报。
- **字幕抓取走双通道**：主通道 yt-dlp（带 `[mm:ss]` 时间戳，优先），失败时由备用 API 通道兜底（纯文本）。判断「这个视频到底有没有字幕」请以主通道或 `--list-subs` 为准，备用通道在 2026-09 之前是坏的，用它探查会给出一片假阴性。
- **画面路径靠抽帧**：`bili_frames.py` 只下载视频 + 抽关键帧，AI 用 Read 逐张读帧（每批 ≤4 张，看不清就 `--width 1920` 重抽）。**严禁拿标题/标签脑补画面冒充"看见"**；整活/鬼畜/实拍类视频信息在画面里时，优先走这条。

## 本仓库结构

```
SKILL.md              # 技能定义（WorkBuddy 加载）
scripts/bili_watch.py # 文本路径：字幕/弹幕/评论/搜索
scripts/bili_frames.py# 画面路径：下载视频 + ffmpeg 抽帧供 AI 读图（v1.2.0 新增）
```

## 更新日记

- **v1.2.3**：修复备用 API 字幕通道 `fetch_subtitle_via_api()` 的三处失效点。① `aid`/`cid` 原先从视频页 HTML 正则抽取，B站改版后恒为空，函数静默 `return None`；改用 `x/web-interface/view` 接口（wbi 签名），网页正则降为保底。② `player/wbi/v2` 用 POST 调用返回 `405 Method Not Allowed`，改为 GET + query string。③ `subtitles` 数组顺序不可信，实测返回 `['ai-zh','ai-en']` 却按序取到 `ai-en`，改为按 `lan` 排序优先中文。**连带发现**：该通道此前用于探测「视频有无字幕」全是假阴性，同一批样本修正后 32 个里 20 个有 `ai-zh`。实测 `BV1w6ZEYrEsb`：主通道 404 行带时间戳，备用通道 4597 字符中文。
- **v1.2.2**：元数据不再依赖浏览器 cookie。`fetch_metadata()` 原先一上来就带 `--cookies-from-browser <默认 firefox>`，新机未装 Firefox 时 yt-dlp 直接报错、stdout 为空，**连公开的标题 / UP主 / 时长 / 播放量也一并丢空**。改为三级降级：先无 cookie 走 `--dump-json` → 失败再带 cookie 重试 → 仍失败退回网页解析。元数据是公开信息，任何时候都不该依赖登录态。
- **v1.2.1**：SKILL.md 补充两个抽帧坑。合集页报 `Unable to extract initial state` 时，加 `--extractor-args "bilibili:download_via_api=true"` 改走 view API；超长视频（数小时纯享版）改用 `ffmpeg -ss 时间点 -frames:v 1` 按点 seek，避免 `fps=1/interval` 完整软解导致卡死。
- **v1.2.0**：新增画面路径 `scripts/bili_frames.py`（下载视频 + ffmpeg 抽关键帧，供 AI 逐张读图看画面）；README 同步补充画面路径说明、能拉什么表新增「画面帧」、用法新增抽帧示例与参数、`关键约束` 章节改名为 `关键提示`。
- **初版**：仅文本路径 `scripts/bili_watch.py`（字幕 / 弹幕 / 评论 / 搜索转写）。
