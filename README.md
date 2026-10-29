# 每日三封信

每天按上海时间发三封信，并把已经发出的正文留在一个公开页面上。收件邮箱只放在 GitHub Actions 的 Secret `DIGEST_TO` 里，不写进仓库，运行日志里也不打印。

| 邮件 | 上海时间 | 内容 |
| --- | --- | --- |
| GitHub 热门项目 | 08:00、18:00 | [github.com/trending](https://github.com/trending) 的今日、本周、本月榜，另加一份中文社区今日榜 |
| 国内外大事 | 08:15、18:15 | 国内 10 条、国外 10 条，每条是打开的报道里的三四句话 |
| 每日想法 | 08:30、18:30 | 10 条，每条三四句话，对照当天的公开报道 |

主题上的时间是实际发出时的上海时间。上午和晚上不是同一组内容。

## 定时任务

`.github/workflows/mail-schedule.yml` 每小时检查四次（UTC 的第 2、17、32、47 分钟，上海时间同样是这四个分钟）。上午三封从各自的点一直开到 12:00，晚上三封开到 23:00。同一天同一档发出去之后不会重发。已发送的档期记在 `mail-state/`。

没设收件人 `DIGEST_TO` 时，任务马上失败，不会先去抓榜单和新闻。

只有默认分支 `main` 上的 workflow 会按计划运行。Actions 里手动运行某一封时会强制再发一次。

私有仓库上，GitHub 仍可能把计划任务推迟一两个小时。上午拖过 12:00、晚上拖过 23:00，那一班当天就不再发。

## 发信

优先走 QQ 邮箱 SMTP（`smtp.qq.com:465`）。邮件是 HTML 加纯文本。没有授权码、并且设置了 `DIGEST_FALLBACK=formsubmit` 时，纯文本交给 [FormSubmit](https://formsubmit.co) 转发。FormSubmit 第一次会先发一封 **Activate Form** 激活信，激活之后下一次任务才送正文。激活信可能在垃圾箱。

在 **Settings → Secrets and variables → Actions** 添加：

- `DIGEST_TO`：收件邮箱。不填则拒绝发信。
- `QQ_SMTP_AUTH_CODE`：QQ 邮箱授权码，不是登录密码。在 QQ 邮箱 → 设置 → 账号 → POP3/IMAP/SMTP 里生成。
- `QQ_SMTP_USER`：可选。不填就用 `DIGEST_TO`。
- `CURSOR_API_KEY`：可选。见下面「时事从哪里来」。

这些值只放在 Secrets 里。`.env` 已被忽略，不要把邮箱、授权码或 API Key 提交进仓库。

本地先看正文、不发信：

```bash
python3 scripts/github_trending_digest.py --html-out digests/latest.html --text-out digests/latest.txt
python3 scripts/major_events.py --text-out digests/events.txt
python3 scripts/daily_ideas.py --text-out digests/ideas.txt
```

本地发信时从环境变量读收件人：

```bash
DIGEST_TO=你的邮箱 QQ_SMTP_AUTH_CODE=你的授权码 python3 scripts/github_trending_digest.py --send
```

## 公开页面

发出去的信留在 `archive/`，页面由 `docs/` 生成。定时任务提交这些文件后，触发 `.github/workflows/publish-page.yml`，部署到：

https://uncle-leung.github.io/daily_thoughts/

页面只展示已经发出的信。2026-10-28 上午 10:17 那三封是页面做好之前发的，只有发送记录，没有正文。之后每一封都会整封留在页面上。

GitHub Free 只给公开仓库提供 Pages。仓库改为公开后，在 **Settings → Pages** 选择 **GitHub Actions**。这一步还没选时，部署会失败，信仍然会发出。

## 时事从哪里来

国内外大事和每日想法在发信前，交给一个没有代码仓库的 Cursor 云端代理。代理必须先 `web_search`，再 `web_fetch` 打开原文，不能靠模型记忆写时事。默认模型是 Grok 4.7（`reasoning_effort=high`，`fast=true`）。

`CURSOR_API_KEY` 在 Cursor Dashboard → API Keys 里创建，然后放进 Actions Secret。没有这把钥匙，或代理没有真正打开网页时，大事和想法退回原来的 RSS，信仍会发。

GitHub 热门项目直接抓取 trending 页面，不走模型。每条排名用仓库简介和 README 整理成两三句中文说明。

发信只走这一套 GitHub Actions。不要再并行开一套会发同一封信的 Cursor Automation。
