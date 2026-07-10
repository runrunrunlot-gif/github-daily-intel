# GitHub Daily Intel

每天从 GitHub 抓取对抖音带货、短视频生产、AI 工具和自动化工作流可能有用的开源项目信息，并生成中文日报。

## 这个项目做什么

- 搜索 AI 视频、图片、自动化、数据采集、电商分析等相关 GitHub 项目
- 按“对抖音带货工作流是否有用”进行初步打分
- 输出每日 Markdown 报告，方便人工快速筛选
- 保留原始 JSON 数据，方便后续复盘和二次分析

## 快速开始

```bash
cd github-daily-intel
python3 scripts/fetch_github_daily.py
```

运行后会生成：

- `daily-reports/YYYY-MM-DD.md`：中文日报
- `data/YYYY-MM-DD.json`：原始抓取和评分数据

## 可选：提高 GitHub 请求额度

不设置 token 也能跑，但 GitHub 未登录请求有频率限制。后续如果每天自动跑，建议设置：

```bash
export GITHUB_TOKEN="你的 GitHub token"
```

## 后续迭代方向

- 接入 AI 总结，把项目 README 自动压缩成“能不能为我所用”
- 增加抖音选品、脚本生成、素材生产的专门评分维度
- 接入 GitHub Actions，每天自动运行并提交报告
- 增加微信、飞书或邮件提醒
- 建立“已测试工具库”和“弃用原因库”

