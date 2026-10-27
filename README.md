# GitHub 热门项目日报

每天 **09:00** 和 **18:00**（上海时间）抓取 GitHub Trending 官方榜的今日、本周、本月排名，整理成邮件发到 `fisherleung27@qq.com`。

数据来自 [github.com/trending](https://github.com/trending)。邮件里还有一份中文社区今日榜（`spoken_language_code=zh`）。

## 定时任务

`.github/workflows/github-trending-digest.yml` 在 GitHub Actions 上运行。Cron 使用 UTC：

| 上海时间 | UTC cron |
| --- | --- |
| 09:00 | `0 1 * * *` |
| 18:00 | `0 10 * * *` |

Actions 的计划任务可能晚几分钟。只有默认分支 `main` 上的 workflow 会按点运行。Actions 页面也可以手动运行 **GitHub trending digest**。

## 发信

优先走 QQ 邮箱 SMTP（`smtp.qq.com:465`），邮件是 HTML 表格加纯文本。

1. 打开 QQ 邮箱 → 设置 → 账号 → 开启 POP3/IMAP/SMTP，生成授权码。授权码不是 QQ 登录密码。
2. 在本仓库 **Settings → Secrets and variables → Actions** 添加：
   - `QQ_SMTP_AUTH_CODE`：授权码
   - `QQ_SMTP_USER`：可选，默认用收件地址 `fisherleung27@qq.com`

授权码还没配时，workflow 会把纯文本榜单交给 [FormSubmit](https://formsubmit.co) 转发。第一封通常是确认链接，点一次之后后续提交才会进收件箱。配好 `QQ_SMTP_AUTH_CODE` 后就不再走 FormSubmit。

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
