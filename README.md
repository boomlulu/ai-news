# AI 每日精选 (AI Daily Digest)

每天自动收集全球 Top AI 公司动态 + 全网 AI 热点，用大白话讲清最值得关注的 10 条新闻。爆点新闻置顶。面向手机竖屏阅读的静态 HTML。

## 结构

- `index.html` — 今天的最新一期（首页）
- `archive/YYYY-MM-DD.html` — 每天的历史归档
- `archive/index.html` — 归档列表
- `.nojekyll` — 让 GitHub Pages 原样发布静态文件

## 部署到 GitHub Pages

本仓库已初始化为本地 git 仓库并完成提交。要发布到网上，在你自己的电脑/账号上执行：

```bash
# 1) 在 GitHub 网站新建一个空仓库，例如 ai-news（不要勾选 README）
# 2) 关联远程并推送（替换成你的用户名/仓库名）
git remote add origin https://github.com/<你的用户名>/ai-news.git
git branch -M main
git push -u origin main

# 3) 在 GitHub 仓库 Settings → Pages → Source 选择 main 分支 / 根目录
#    几分钟后即可通过 https://<你的用户名>.github.io/ai-news/ 访问
```

> 说明：本次自动运行环境没有 GitHub 登录凭证，因此只完成了本地 git 提交。
> 推送到远程需要你完成一次上面的授权（仅需一次，之后定时任务可自动 commit）。

## 免责声明

新闻经多源交叉核对；模型版本号、价格等以各公司官方为准。标注"泄露/传闻"的内容尚未获官方证实。
