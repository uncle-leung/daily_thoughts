# GitHub 热门项目日报

每天 **09:00** 和 **18:00**（上海时间）抓取 GitHub Trending 官方榜的今日、本周、本月排名，整理成邮件发到 Secret `DIGEST_TO` 里的邮箱。邮箱不写进仓库。

数据来自 [github.com/trending](https://github.com/trending)。每条排名用仓库简介和 README 整理成两三句中文说明。邮件里还有一份中文社区今日榜（`spoken_language_code=zh`）。

## 定时任务

`.github/workflows/mail-schedule.yml` 每小时检查四次（UTC 的第 2、17、32、47 分钟）。每封信只在对应上海时间过后的 100 分钟内发送一次，同一天同一档不会重发：

| 邮件 | 上海时间 |
| --- | --- |
| GitHub 热门项目 | 09:00、18:00 |
| 国内外大事 | 09:15、18:15 |
| 每日想法 | 09:30、18:30 |

主题上的时间是实际发出时的上海时间。超过 100 分钟才跑起来的任务直接跳过，不会把深夜补跑标成 18:00。已发送的档期记在 `mail-state/`。只有默认分支 `main` 上的 workflow 会按计划运行。Actions 里手动运行某一封时会强制再发一次。

GitHub 在私有仓库上仍可能把计划任务推迟一两个小时。推迟超过 100 分钟的那一班当天就不会再发。

## 每日想法

每天 **09:30** 和 **18:30**（上海时间）另发一封邮件，收件人同样是 `DIGEST_TO`。

每封 10 条，每条三四句话。内容对照当天的公开报道，覆盖人工智能、社会变化、工作、健康、财富和时事，不是一套固定的人生清单。上午和晚上用不同的报道。配了 `CURSOR_API_KEY` 时，由 Cursor 云端代理联网检索后再写；报道暂时取不到时，用若干条和这个时代有关的判断补足。

```bash
python3 scripts/daily_ideas.py --text-out digests/ideas.txt
```

## 国内外大事

每天 **09:15** 和 **18:15**（上海时间）再发一封邮件，收件人同样是 `DIGEST_TO`。

每封有国内大事 10 条、国外大事 10 条。每条是当场打开的报道里的三四句话。上午和晚上不是同一组。配了 `CURSOR_API_KEY` 时，由 Cursor 云端代理联网检索；没有钥匙或检索不够时，仍摘自中国新闻网。

```bash
python3 scripts/major_events.py --text-out digests/events.txt
```

## 发信

优先走 QQ 邮箱 SMTP（`smtp.qq.com:465`），邮件是 HTML 表格加纯文本。

1. 打开 QQ 邮箱 → 设置 → 账号 → 开启 POP3/IMAP/SMTP，生成授权码。授权码不是 QQ 登录密码。
2. 在本仓库 **Settings → Secrets and variables → Actions** 添加：
   - `DIGEST_TO`：收件邮箱
   - `QQ_SMTP_AUTH_CODE`：授权码
   - `QQ_SMTP_USER`：可选，不填就用 `DIGEST_TO`

授权码还没配时，workflow 会把纯文本榜单交给 [FormSubmit](https://formsubmit.co) 转发。第一次会先往邮箱发一封 **Activate Form** 激活信，点开链接之后，下一次任务才会把榜单正文送进来。激活信可能在垃圾箱。配好 `QQ_SMTP_AUTH_CODE` 后就不再走 FormSubmit，邮件会是完整的 HTML 表格。

本地试跑：

```bash
python3 scripts/github_trending_digest.py --html-out digests/latest.html --text-out digests/latest.txt
QQ_SMTP_AUTH_CODE=你的授权码 python3 scripts/github_trending_digest.py --send
```

## 和 Cursor 的关系

国内外大事和每日想法在发信前，交给一个没有代码仓库的 Cursor 云端代理。代理必须先 `web_search`，再 `web_fetch` 打开原文，不能靠模型记忆写时事。默认模型是 Grok 4.7（`reasoning_effort=high`，`fast=true`）。

在本仓库 **Settings → Secrets and variables → Actions** 添加 `CURSOR_API_KEY`（Cursor Dashboard → API Keys）。可选变量不用加，工作流里已经写死 `CURSOR_MODEL=grok-4.7`。没有这把钥匙，或代理没有真正打开网页时，大事和想法退回原来的 RSS，信仍会发。

GitHub 热门项目仍直接抓取 trending 页面，不走模型。

发信还是这一套 GitHub Actions。不要再并行开一套会发同一封信的 Cursor Automation。
