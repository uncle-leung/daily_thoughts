# GitHub 热门项目日报

每天 **09:00** 和 **18:00**（上海时间）抓取 GitHub Trending 官方榜的今日、本周、本月排名，整理成邮件发到 ``。

数据来自 [github.com/trending](https://github.com/trending)。每条排名用仓库简介和 README 整理成两三句中文说明。邮件里还有一份中文社区今日榜（`spoken_language_code=zh`）。

## 定时任务

`.github/workflows/github-trending-digest.yml` 在 GitHub Actions 上运行。Cron 使用 UTC：

| 上海时间 | UTC cron |
| --- | --- |
| 09:00 | `0 1 * * *` |
| 18:00 | `0 10 * * *` |

Actions 的计划任务可能晚几分钟。只有默认分支 `main` 上的 workflow 会按点运行。Actions 页面也可以手动运行 **GitHub trending digest**。

## 每日想法

`.github/workflows/daily-ideas.yml` 在每天 **09:30** 和 **18:30**（上海时间）另发一封邮件，同样到 ``。

每封 10 条，每条三四句话。内容对照当天的公开报道，覆盖人工智能、社会变化、工作、健康、财富和时事，不是一套固定的人生清单。上午和晚上用不同的报道。对应 UTC cron 是 `30 1 * * *` 和 `30 10 * * *`。报道暂时取不到时，用若干条和这个时代有关的判断补足。

```bash
python3 scripts/daily_ideas.py --text-out digests/ideas.txt
```

## 发信

优先走 QQ 邮箱 SMTP（`smtp.qq.com:465`），邮件是 HTML 表格加纯文本。

1. 打开 QQ 邮箱 → 设置 → 账号 → 开启 POP3/IMAP/SMTP，生成授权码。授权码不是 QQ 登录密码。
2. 在本仓库 **Settings → Secrets and variables → Actions** 添加：
   - `QQ_SMTP_AUTH_CODE`：授权码
   - `QQ_SMTP_USER`：可选，默认用收件地址 ``

授权码还没配时，workflow 会把纯文本榜单交给 [FormSubmit](https://formsubmit.co) 转发。第一次会先往邮箱发一封 **Activate Form** 激活信，点开链接之后，下一次任务才会把榜单正文送进来。激活信可能在垃圾箱。配好 `QQ_SMTP_AUTH_CODE` 后就不再走 FormSubmit，邮件会是完整的 HTML 表格。

本地试跑：

```bash
python3 scripts/github_trending_digest.py --html-out digests/latest.html --text-out digests/latest.txt
QQ_SMTP_AUTH_CODE=你的授权码 python3 scripts/github_trending_digest.py --send
```

## 和 Cursor 的关系

抓取和发信是固定流程，放在 GitHub Actions 里每天跑两次，不消耗 Cursor 模型额度。

如果希望改由 Cursor Automation 触发，在 [cursor.com/automations](https://cursor.com/automations) 新建定时任务，Cron 填：

```text
CRON_TZ=Asia/Shanghai 0 9,18 * * *
```

提示词可以写成：在 `uncle-leung/daily_thoughts` 里执行 `python3 scripts/github_trending_digest.py --send`。云端环境需要有 `QQ_SMTP_AUTH_CODE`。不要和上面的 GitHub Actions 同时开，否则每天会收到两封。
