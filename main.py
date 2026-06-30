#!/usr/bin/env python3
"""
Daily AI News Push – GitHub Actions
Fetches latest AI news (focus: AI coding + embodied intelligence),
translates to Chinese, generates a summary report, and sends via QQ Mail.
"""

import os
import re
import smtplib
import time
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen
from urllib.parse import quote
from xml.etree import ElementTree as ET
import html

# ── configuration ──────────────────────────────────────────────
QQ_EMAIL = os.environ["QQ_EMAIL"]
QQ_SMTP_CODE = os.environ["QQ_SMTP_CODE"]
RECIPIENT = os.environ.get("RECIPIENT", QQ_EMAIL)

TZ = timezone(timedelta(hours=8))  # Beijing time

QUERIES = [
    ("AI coding agent programming tool", "AI编程"),
    ("humanoid robot embodied intelligence", "具身智能"),
    ("large language model LLM release", "大模型"),
    ("OpenAI Anthropic Google AI news", "AI动态"),
]

BOOST_KEYWORDS = [
    "cursor", "copilot", "claude", "gpt", "gemini", "grok",
    "coding agent", "ai agent", "humanoid", "embodied",
    "具身", "人形机器人", "编程", "开发者",
]

MAX_RESULTS = 5


# ── helpers ─────────────────────────────────────────────────────

def fetch_rss(url: str, label: str, timeout: int = 15) -> list:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; NewsBot/1.0)"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            tree = ET.parse(resp)
    except Exception as e:
        print(f"  [WARN] RSS failed '{label}': {e}")
        return []

    articles = []
    for item in tree.iter("item"):
        title_el = item.find("title")
        link_el = item.find("link")
        desc_el = item.find("description")
        source_el = item.find("source")

        title_str = (title_el.text or "").strip() if title_el is not None else ""
        link_str = (link_el.text or "").strip() if link_el is not None else ""
        desc_str = (desc_el.text or "").strip() if desc_el is not None else ""
        source_str = (source_el.text or "").strip() if source_el is not None else label

        title_str = re.sub(r"\s*-\s*[\w\s]+$", "", title_str).strip()
        title_str = html.unescape(title_str)
        desc_str = html.unescape(desc_str)
        desc_str = re.sub(r"<[^>]+>", "", desc_str).strip()

        if not title_str or len(title_str) < 8:
            continue

        articles.append({
            "title": title_str,
            "link": link_str,
            "description": desc_str[:300],
            "source": source_str,
        })

    return articles


def fetch_google_news(query: str, count: int = 10) -> list:
    url = (
        f"https://news.google.com/rss/search"
        f"?q={quote(query)}&hl=en-US&gl=US&ceid=US:en&num={count}"
    )
    return fetch_rss(url, f"Google/{query}")


def fetch_hackernews() -> list:
    url = "https://hnrss.org/newest?q=AI+LLM+robot+coding+agent&count=20"
    return fetch_rss(url, "HackerNews")


def score_article(article: dict) -> float:
    title_lower = article["title"].lower()
    desc_lower = article.get("description", "").lower()
    combined = title_lower + " " + desc_lower
    score = 0.0
    for kw in BOOST_KEYWORDS:
        if kw.lower() in combined:
            score += 3.0
    if article.get("description") and len(article["description"]) > 50:
        score += 2.0
    return score


def deduplicate(articles: list) -> list:
    seen = set()
    result = []
    for a in articles:
        key = a["title"].lower()[:40]
        if key not in seen:
            seen.add(key)
            result.append(a)
    return result


def fetch_all_news() -> list:
    all_articles = []

    for query, label in QUERIES:
        print(f"  fetching: {label}")
        articles = fetch_google_news(query)
        for a in articles:
            a["score"] = score_article(a)
        all_articles.extend(articles)
        time.sleep(1)

    print("  fetching: Hacker News")
    articles = fetch_hackernews()
    for a in articles:
        a["score"] = score_article(a)
    all_articles.extend(articles)

    all_articles = deduplicate(all_articles)
    all_articles.sort(key=lambda a: a.get("score", 0), reverse=True)
    return all_articles[:MAX_RESULTS]


# ── translation ──────────────────────────────────────────────────

def translate_to_zh(text: str) -> str:
    """Translate text to Chinese using Google Translate free endpoint."""
    if not text or len(text.strip()) < 3:
        return text
    text = text[:500]
    try:
        encoded = quote(text, safe="")
        url = (
            f"https://translate.googleapis.com/translate_a/single"
            f"?client=gtx&sl=en&tl=zh-CN&dt=t&q={encoded}"
        )
        req = Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "application/json",
        })
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        if data and len(data) > 0 and data[0]:
            translated = "".join([seg[0] for seg in data[0] if seg[0]])
            return translated
    except Exception as e:
        print(f"    [translate WARN] {e}")
    return text


def translate_article(article: dict) -> dict:
    a = dict(article)
    print(f"    translating: {article['title'][:40]}...")
    a["title_zh"] = translate_to_zh(a["title"])
    time.sleep(0.3)
    if a.get("description"):
        a["description_zh"] = translate_to_zh(a["description"])
        time.sleep(0.3)
    else:
        a["description_zh"] = ""
    return a


# ── email builder ───────────────────────────────────────────────

def build_email_html(articles: list) -> str:
    now = datetime.now(TZ)
    date_str = now.strftime("%Y年%m月%d日")

    rows = ""
    for i, a in enumerate(articles, 1):
        title = a.get("title_zh") or a["title"]
        desc = a.get("description_zh") or a.get("description", "")
        link = a.get("link", "#")
        source = a.get("source", "")

        desc_clean = desc[:250].replace("\n", " ").strip()
        if len(desc) > 250:
            desc_clean += "..."

        rows += f"""
        <tr>
            <td style="padding:20px 16px;border-bottom:1px solid #f0f0f0;">
                <div style="display:flex;align-items:flex-start;gap:12px;">
                    <span style="flex-shrink:0;width:28px;height:28px;line-height:28px;
                                 background:#1677ff;color:#fff;border-radius:6px;
                                 text-align:center;font-size:13px;font-weight:bold;">
                        {i}
                    </span>
                    <div style="flex:1;">
                        <a href="{link}" style="color:#1a1a1a;text-decoration:none;
                              font-size:15px;font-weight:600;line-height:1.5;"
                           target="_blank">{title}</a>
                        <p style="margin:8px 0 4px;color:#444;font-size:13px;
                                  line-height:1.7;text-align:justify;">{desc_clean}</p>
                        <span style="color:#999;font-size:12px;">来源：{source}</span>
                    </div>
                </div>
            </td>
        </tr>"""

    if not rows:
        rows = """
        <tr><td style="padding:24px;text-align:center;color:#999;">
            今日暂未抓取到相关新闻，请稍后查看。
        </td></tr>"""

    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
</head>
<body style="margin:0;padding:16px;background:#f5f6fa;
             font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
    <div style="max-width:680px;margin:0 auto;">
        <div style="background:linear-gradient(135deg,#1677ff 0%,#0958d9 100%);
                    padding:24px 20px;border-radius:12px 12px 0 0;">
            <h1 style="color:#fff;margin:0;font-size:20px;font-weight:700;">
                🤖 AI 领域每日速递</h1>
            <p style="color:rgba(255,255,255,0.85);margin:8px 0 0;font-size:13px;">
                {date_str} · 聚焦 AI Coding 与具身智能 · 中文摘要版</p>
        </div>
        <table style="width:100%;border-collapse:collapse;background:#fff;
                      border-radius:0 0 12px 12px;box-shadow:0 2px 8px rgba(0,0,0,0.08);">
            <tbody>{rows}</tbody>
        </table>
        <p style="color:#aaa;font-size:11px;text-align:center;margin-top:16px;">
            由 GitHub Actions 自动发送 · 每日 08:00（北京时间）</p>
    </div>
</body>
</html>"""


def send_email(html_content: str):
    msg = MIMEMultipart("alternative")
    now = datetime.now(TZ)
    msg["Subject"] = f"🤖 AI 速递 | {now.strftime('%m/%d')} · AI Coding & 具身智能"
    msg["From"] = QQ_EMAIL
    msg["To"] = RECIPIENT
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    print(f"  sending to {RECIPIENT} ...")
    with smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=15) as server:
        server.login(QQ_EMAIL, QQ_SMTP_CODE)
        server.sendmail(QQ_EMAIL, [RECIPIENT], msg.as_string())
    print("  ✓ email sent!")


# ── main ────────────────────────────────────────────────────────

def main():
    print("=" * 50)
    print("  Daily AI News Push (Chinese Report)")
    print(f"  {datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')} (Beijing)")
    print("=" * 50)

    print("\n[1/4] Fetching news from multiple sources ...")
    articles = fetch_all_news()

    if not articles:
        print("  [WARN] No articles found.")
        articles = [{
            "title": "今日暂未抓取到 AI 相关新闻",
            "title_zh": "今日暂未抓取到 AI 相关新闻",
            "link": "https://news.google.com/search?q=AI",
            "description": "",
            "description_zh": "",
            "source": "系统通知",
            "score": 0,
        }]

    print(f"\n[2/4] Got {len(articles)} articles, translating to Chinese ...")
    translated = []
    for a in articles:
        translated.append(translate_article(a))

    print(f"\n[3/4] Building Chinese report email ...")
    html = build_email_html(translated)

    print("[4/4] Sending via QQ Mail ...")
    send_email(html)

    print("\n✓ Done!")


if __name__ == "__main__":
    main()
