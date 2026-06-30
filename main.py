#!/usr/bin/env python3
"""
Daily AI News Push – GitHub Actions
Fetches latest AI news (focus: AI coding + embodied intelligence),
generates a summary, and sends it via QQ Mail.
"""

import os
import re
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen
from urllib.parse import quote
from xml.etree import ElementTree as ET


# ── configuration ──────────────────────────────────────────────
QQ_EMAIL = os.environ["QQ_EMAIL"]          # your QQ email
QQ_SMTP_CODE = os.environ["QQ_SMTP_CODE"]  # SMTP authorization code
RECIPIENT = os.environ.get("RECIPIENT", QQ_EMAIL)

# search queries (Google News RSS)
QUERIES = [
    ("AI coding agent tool", "AI编程"),
    ("embodied intelligence robot humanoid", "具身智能/人形机器人"),
    ("large language model release latest", "大模型发布"),
    ("OpenAI Anthropic AI news", "OpenAI/Anthropic动态"),
]

# keyword boost (title contains these → higher priority)
PRIORITY_KEYWORDS = [
    "coding agent", "cursor", "copilot", "agentic coding", "code generation",
    "humanoid robot", "embodied", "具身智能", "人形机器人", "机器人",
    "GPT", "Claude", "Gemini", "Grok", "开源", "open source",
    "programming", "developer", "coding",
]

MAX_RESULTS = 8
TZ = timezone(timedelta(hours=8))  # Beijing time


# ── helpers ─────────────────────────────────────────────────────

def fetch_google_news(query: str, count: int = 10) -> list[dict]:
    """Fetch news articles from Google News RSS."""
    url = f"https://news.google.com/rss/search?q={quote(query)}&hl=en-US&gl=US&ceid=US:en&num={count}"
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(req, timeout=15) as resp:
            tree = ET.parse(resp)
    except Exception as e:
        print(f"  [WARN] Google News fetch failed for '{query}': {e}")
        return []

    articles = []
    for item in tree.iter("item"):
        title = item.find("title")
        link = item.find("link")
        pubdate = item.find("pubDate")
        source = item.find("source")

        title_str = title.text if title is not None else ""
        link_str = link.text if link is not None else ""
        source_str = source.text if source is not None else ""

        # Google News titles have " - Source" suffix
        title_str = re.sub(r"\s*-\s*\S+$", "", title_str).strip()

        if not title_str or len(title_str) < 10:
            continue

        articles.append({
            "title": title_str,
            "link": link_str,
            "source": source_str,
        })

    return articles


def score_article(article: dict) -> float:
    """Score an article by relevance to AI coding / embodied intelligence."""
    title_lower = article["title"].lower()
    source_lower = article.get("source", "").lower()
    score = 0.0

    # keyword scoring
    kws = [
        ("ai cod", 5.0), ("coding agent", 5.0), ("agentic", 4.0),
        ("cursor", 5.0), ("copilot", 4.0), ("code complet", 3.0),
        ("developer tool", 3.0), ("programming", 3.0),
        ("humanoid robot", 5.0), ("embodied", 5.0),
        ("具身智能", 5.0), ("人形机器人", 5.0), ("机器人", 3.0),
        ("gpt", 4.0), ("claude", 4.0), ("openai", 4.0),
        ("anthropic", 4.0), ("gemini", 3.0), ("grok", 3.0),
        ("llama", 3.0), ("open source", 3.0), ("开源", 3.0),
        ("foundation model", 3.0), ("benchmark", 2.0),
    ]
    for kw, weight in kws:
        if kw in title_lower or kw in source_lower:
            score += weight

    return score


def deduplicate(articles: list[dict]) -> list[dict]:
    """Remove near-duplicate articles."""
    seen = set()
    result = []
    for a in articles:
        key = a["title"].lower()[:40]
        if key not in seen:
            seen.add(key)
            result.append(a)
    return result


def fetch_all_news() -> list[dict]:
    """Fetch news from all queries, score, and return top results."""
    all_articles = []
    for query, label in QUERIES:
        print(f"  fetching: {label}")
        articles = fetch_google_news(query, count=10)
        for a in articles:
            a["score"] = score_article(a)
        all_articles.extend(articles)
        time.sleep(1)  # be polite

    # deduplicate
    all_articles = deduplicate(all_articles)

    # sort by score desc, take top
    all_articles.sort(key=lambda a: a["score"], reverse=True)
    return all_articles[:MAX_RESULTS]


def build_email_html(articles: list[dict]) -> str:
    """Build a clean HTML email from articles."""
    now = datetime.now(TZ)
    date_str = now.strftime("%Y年%m月%d日")

    items_html = ""
    for i, a in enumerate(articles, 1):
        items_html += f"""
        <tr>
            <td style="padding:12px 16px;border-bottom:1px solid #eee;vertical-align:top;">
                <span style="display:inline-block;min-width:24px;height:24px;line-height:24px;
                             background:#1677ff;color:#fff;border-radius:4px;text-align:center;
                             font-size:13px;font-weight:bold;margin-right:8px;">{i}</span>
            </td>
            <td style="padding:12px 8px;border-bottom:1px solid #eee;">
                <a href="{a['link']}" style="color:#1677ff;text-decoration:none;font-size:15px;font-weight:500;"
                   target="_blank">{a['title']}</a>
                <br><span style="color:#999;font-size:12px;">{a.get('source', '')}</span>
            </td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
             max-width:680px;margin:0 auto;color:#333;">
    <div style="background:#1677ff;padding:24px 16px;border-radius:8px 8px 0 0;">
        <h1 style="color:#fff;margin:0;font-size:22px;">🤖 AI 领域每日速递</h1>
        <p style="color:rgba(255,255,255,0.85);margin:6px 0 0;font-size:13px;">
            {date_str} · 聚焦 AI Coding 与具身智能</p>
    </div>
    <table style="width:100%;border-collapse:collapse;background:#fff;
                  border-radius:0 0 8px 8px;box-shadow:0 1px 4px rgba(0,0,0,0.1);">
        <tbody>{items_html}</tbody>
    </table>
    <p style="color:#aaa;font-size:11px;text-align:center;margin-top:16px;">
        本邮件由 GitHub Actions 自动发送 · 每日 22:00 (北京时间)</p>
</body>
</html>"""


def send_email(html_content: str):
    """Send email via QQ Mail SMTP."""
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
    print("  Daily AI News Push")
    print(f"  {datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')} (Beijing)")
    print("=" * 50)

    print("\n[1/3] Fetching news from multiple sources ...")
    articles = fetch_all_news()

    if not articles:
        print("  [WARN] No articles found. Sending fallback notice.")
        articles = [{
            "title": "今日暂未抓取到 AI 相关新闻，请稍后手动查看。",
            "link": "https://news.google.com/search?q=AI",
            "source": "Google News",
        }]

    print(f"  got {len(articles)} articles\n")
    for a in articles:
        print(f"    [{a['score']:.1f}] {a['title']}")

    print("\n[2/3] Building email ...")
    html = build_email_html(articles)

    print("[3/3] Sending via QQ Mail ...")
    send_email(html)

    print("\n✓ Done!")


if __name__ == "__main__":
    main()
