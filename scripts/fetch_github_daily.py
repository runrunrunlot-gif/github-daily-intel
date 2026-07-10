#!/usr/bin/env python3
"""Fetch GitHub repository signals and generate a Chinese daily intel report."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "sources.json"
REPORTS_DIR = ROOT / "daily-reports"
DATA_DIR = ROOT / "data"


def load_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def github_get(path: str, token: str | None) -> dict:
    url = f"https://api.github.com{path}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "github-daily-intel",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        if "CERTIFICATE_VERIFY_FAILED" not in str(exc):
            raise

        # Some local Python builds miss the system CA bundle. Retry only for
        # this specific certificate-chain failure so the daily job can run.
        context = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=30, context=context) as response:
            return json.loads(response.read().decode("utf-8"))


def search_repositories(query: str, max_results: int, min_stars: int, token: str | None) -> list[dict]:
    full_query = f"({query}) stars:>={min_stars}"
    encoded = urllib.parse.urlencode(
        {
            "q": full_query,
            "sort": "updated",
            "order": "desc",
            "per_page": max_results,
        }
    )
    payload = github_get(f"/search/repositories?{encoded}", token)
    return payload.get("items", [])


def score_repo(repo: dict, positive_keywords: list[str], negative_keywords: list[str]) -> tuple[int, list[str]]:
    text = " ".join(
        str(repo.get(k) or "")
        for k in ["name", "full_name", "description", "language", "topics"]
    ).lower()

    stars = int(repo.get("stargazers_count") or 0)
    forks = int(repo.get("forks_count") or 0)
    watchers = int(repo.get("watchers_count") or 0)
    open_issues = int(repo.get("open_issues_count") or 0)

    score = 0
    reasons: list[str] = []

    if stars >= 5000:
        score += 25
        reasons.append("社区关注很高")
    elif stars >= 1000:
        score += 18
        reasons.append("社区关注较高")
    elif stars >= 200:
        score += 10
        reasons.append("已有一定关注")

    if forks >= 300:
        score += 10
        reasons.append("二次开发活跃")
    elif forks >= 50:
        score += 5
        reasons.append("有人在复用")

    if watchers >= 100:
        score += 5

    matched = sorted({kw for kw in positive_keywords if kw.lower() in text})
    if matched:
        score += min(30, len(matched) * 5)
        reasons.append("命中关键词：" + "、".join(matched[:6]))

    negative = sorted({kw for kw in negative_keywords if kw.lower() in text})
    if negative:
        score -= 20
        reasons.append("风险词：" + "、".join(negative[:4]))

    if open_issues > 500 and stars < 1000:
        score -= 8
        reasons.append("问题较多，需谨慎测试")

    pushed_at = repo.get("pushed_at") or ""
    try:
        pushed = dt.datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
        age_days = (dt.datetime.now(dt.timezone.utc) - pushed).days
        if age_days <= 14:
            score += 15
            reasons.append("最近两周有更新")
        elif age_days <= 90:
            score += 8
            reasons.append("最近三个月有更新")
        elif age_days > 365:
            score -= 15
            reasons.append("超过一年未更新")
    except ValueError:
        pass

    return max(score, 0), reasons


def simplify_repo(repo: dict, source_name: str, source_why: str, score: int, reasons: list[str]) -> dict:
    return {
        "source": source_name,
        "source_why": source_why,
        "name": repo.get("full_name"),
        "description": repo.get("description") or "",
        "url": repo.get("html_url"),
        "stars": repo.get("stargazers_count") or 0,
        "forks": repo.get("forks_count") or 0,
        "language": repo.get("language") or "Unknown",
        "topics": repo.get("topics") or [],
        "updated_at": repo.get("pushed_at") or repo.get("updated_at"),
        "score": score,
        "reasons": reasons,
    }


def recommendation(score: int) -> str:
    if score >= 65:
        return "重点跟进"
    if score >= 40:
        return "可以测试"
    return "先收藏观察"


def render_repo_line(item: dict, index: int) -> str:
    reasons = "；".join(item["reasons"][:3]) or "暂无明显信号"
    return (
        f"{index}. [{item['name']}]({item['url']}) - {recommendation(item['score'])}\n"
        f"   - 分数：{item['score']} | Stars：{item['stars']} | 语言：{item['language']} | 更新：{item['updated_at']}\n"
        f"   - 简介：{item['description'] or '无简介'}\n"
        f"   - 判断：{reasons}"
    )


def build_report(date_text: str, title: str, grouped: dict[str, list[dict]], all_items: list[dict]) -> str:
    top_items = sorted(all_items, key=lambda x: (x["score"], x["stars"]), reverse=True)[:10]
    strong = [item for item in top_items if item["score"] >= 65]

    if strong:
        summary = f"今天发现 {len(strong)} 个值得重点跟进的项目，优先看视频/图片生产、浏览器自动化、电商评论分析方向。"
    elif top_items:
        summary = "今天没有特别强的项目，但有一些可以收藏观察或小范围测试的工具线索。"
    else:
        summary = "今天没有抓到有效项目，可能是网络、GitHub 限流或关键词需要调整。"

    top_md = "\n\n".join(render_repo_line(item, i + 1) for i, item in enumerate(top_items)) or "暂无。"

    section_blocks = []
    for source_name, items in grouped.items():
        if not items:
            section_blocks.append(f"### {source_name}\n\n暂无结果。")
            continue
        lines = "\n\n".join(render_repo_line(item, i + 1) for i, item in enumerate(items[:5]))
        section_blocks.append(f"### {source_name}\n\n{lines}")

    next_steps = "\n".join(
        [
            "1. 先打开“重点跟进”的项目，看 README 是否有演示图、安装方式、最近提交记录。",
            "2. 把能服务抖音选品、素材生成、脚本生产、数据采集的项目加入测试清单。",
            "3. 对看起来可用的项目，下一步让 Codex 帮你本地试跑或改成自己的工作流。",
        ]
    )

    template = (ROOT / "templates" / "report-template.md").read_text(encoding="utf-8")
    return template.format(
        date=date_text,
        title=title,
        summary=summary,
        top_items=top_md,
        sections="\n\n".join(section_blocks),
        next_steps=next_steps,
    )


def run(date_text: str | None = None) -> pathlib.Path:
    config = load_config()
    token = os.getenv("GITHUB_TOKEN")
    date_text = date_text or dt.datetime.now().strftime("%Y-%m-%d")

    grouped: dict[str, list[dict]] = {}
    all_items_by_url: dict[str, dict] = {}

    for source in config["queries"]:
        name = source["name"]
        grouped[name] = []
        grouped_by_url: dict[str, dict] = {}
        query_values = source.get("queries") or [source["query"]]

        for query in query_values:
            try:
                repos = search_repositories(
                    query,
                    int(config.get("max_results_per_query", 8)),
                    int(config.get("min_stars", 20)),
                    token,
                )
            except Exception as exc:
                grouped_by_url[f"error:{query}"] = {
                    "source": name,
                    "source_why": source.get("why", ""),
                    "name": f"抓取失败：{name} / {query}",
                    "description": str(exc),
                    "url": "https://github.com/search",
                    "stars": 0,
                    "forks": 0,
                    "language": "Unknown",
                    "topics": [],
                    "updated_at": "",
                    "score": 0,
                    "reasons": ["请检查网络、GitHub 限流或 token"],
                }
                continue

            for repo in repos:
                score, reasons = score_repo(repo, config["positive_keywords"], config["negative_keywords"])
                item = simplify_repo(repo, name, source.get("why", ""), score, reasons)
                current_group_item = grouped_by_url.get(item["url"])
                if current_group_item is None or item["score"] > current_group_item["score"]:
                    grouped_by_url[item["url"]] = item

                current = all_items_by_url.get(item["url"])
                if current is None or item["score"] > current["score"]:
                    all_items_by_url[item["url"]] = item

        grouped[name] = list(grouped_by_url.values())
        grouped[name].sort(key=lambda x: (x["score"], x["stars"]), reverse=True)
        time.sleep(1)

    all_items = list(all_items_by_url.values())
    payload = {
        "date": date_text,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "config": config,
        "items": all_items,
        "grouped": grouped,
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    data_path = DATA_DIR / f"{date_text}.json"
    report_path = REPORTS_DIR / f"{date_text}.md"
    data_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(build_report(date_text, config["report_title"], grouped, all_items), encoding="utf-8")
    return report_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate GitHub daily intel report.")
    parser.add_argument("--date", help="Report date, e.g. 2026-07-07")
    args = parser.parse_args()

    report_path = run(args.date)
    print(f"Report written: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
