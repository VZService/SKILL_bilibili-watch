# bili-watch

把 B站（Bilibili）视频转成可阅读文本，让 AI 能读懂视频内容并总结、问答、生成文档。

> WorkBuddy 用户级技能（SKILL.md），也可独立作为脚本使用。

## 能拉什么

| 数据 | 说明 | 是否需登录 |
|---|---|---|
| AI 字幕 | 优先抓取，带 `[mm:ss]` 时间戳 | 需要（Firefox 登录态） |
| 弹幕 | **百分百输出**，带时间戳、可折叠重复 | 不需要 |
| 评论 | 公开评论，含子回复 | 不需要 |
| 元数据 | 标题 / UP主 / 时长 / 播放 / 分区 / 标签 / 简介 | 不需要 |

## 用法

```bash
# 转写单个视频（默认 Firefox 登录态抓字幕，弹幕始终输出）
python bili_watch.py BV1cj8c6jE7f --comments

# 按关键词搜索视频（本机已登录或 --cookies 才能拿列表）
python bili_watch.py "Linux 修复 bug" --search --search-limit 10

# 落盘保存（默认不保存）
python bili_watch.py BV1cj8c6jE7f --save
```

参数：

- `--browser firefox`：读哪个浏览器登录态（默认 firefox；Chrome/Edge 因 DPAPI 加密会失败）
- `--cookies 文件`：Netscape 格式 cookie 文件（一般不推荐，SESSDATA 易失效）
- `--comments`：额外拉取公开评论；`--comment-pages` 翻页上限、`--comment-mode` 2=热度/3=时间
- `--search`：把 target 当关键词搜索；`--search-limit`、`--search-order`
- `--min-danmaku N`：弹幕折叠阈值，默认 2（出现 >= N 次折叠成 `xN`，全部保留）
- `--no-danmaku`：关闭弹幕输出
- `--save`：保存为 `<BVID>.transcript.txt`

## 关键约束

- **字幕锁登录**：B站字幕需登录，`--cookies-from-browser firefox` 最稳；Chrome/Edge 因 App-Bound Encryption 读不出 cookie。
- **弹幕是重点**：无论有无字幕，弹幕都输出（这是对「无字幕视频只看弹幕」的升级——弹幕不再是退路）。
- **无字幕 ≠ 未登录**：脚本会先 `--list-subs` 探查真实轨道，区分「视频本来没字幕」和「登录态没读到」，不再误报。

## 本仓库结构

```
SKILL.md              # 技能定义（WorkBuddy 加载）
scripts/bili_watch.py # 核心脚本：字幕/弹幕/评论/搜索
```

## 来源

由 VZService 团队维护
