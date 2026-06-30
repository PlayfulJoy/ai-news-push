#!/usr/bin/env python3
"""
Daily AI News Push - GitHub Actions
Fetches AI news, reads full article content, translates to Chinese,
and sends a pure-text report email (NO links).
"""

import os, re, sys, time, json, html
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen
from urllib.parse import quote

# ── config ──────────────────────────────────────────────────────
QQ_EMAIL    = os.environ["QQ_EMAIL"]
QQ_SMTP_CODE = os.environ["QQ_SMTP_CODE"]
RECIPIENT   = os.environ.get("RECIPIENT", QQ_EMAIL)
TZ          = timezone(timedelta(hours=8))

QUERIES = [
    ("AI coding agent tool development 2026",  "AI编程"),
    ("humanoid robot embodied intelligence",  "具身智能"),
    ("large language model LLM release news",  "大模型"),
    ("OpenAI Anthropic Google DeepMind AI",    "AI动态"),
]

BOOST_KW = [
    "cursor","copilot","claude","gpt","gemini","grok",
    "coding agent","ai agent","humanoid","embodied",
    "robot","developer","tool","release","launch",
]

MAX_ARTICLES    = 5
FETCH_TIMEOUT   = 12
ARTICLE_TIMEOUT = 10
MAX_SUMMARY_LEN = 600  # characters of translated summary per article

UA = "Mozilla/5.0 (compatible; NewsBot/1.0; +https://github.com/ai-news-push)"

# ── RSS fetching ─────────────────────────────────────────────────

def fetch_google_news_rss(query: str) -> list:
    """Fetch Google News RSS, return list of {title, link, source, pub_date}."""
    url = (f"https://news.google.com/rss/search"
           f"?q={quote(query)}&hl=en-US&gl=US&ceid=US:en")
    req = Request(url, headers={"User-Agent": UA})
    try:
        with urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            raw = resp.read()
    except Exception as e:
        print(f"  [WARN] Google News RSS failed: {e}")
        return []

    # Use regex instead of xml.etree to handle malformed RSS
    items = re.findall(r"<item>(.*?)</item>", raw.decode("utf-8", errors="replace"), re.DOTALL)
    articles = []
    for item_xml in items:
        title_m = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", item_xml, re.DOTALL)
        link_m  = re.search(r"<link>(.*?)</link>", item_xml)
        src_m   = re.search(r"<source[^>]*>(.*?)</source>", item_xml)
        date_m  = re.search(r"<pubDate>(.*?)</pubDate>", item_xml)
        desc_m  = re.search(r"<description>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>", item_xml, re.DOTALL)

        if not title_m or not link_m:
            continue

        title  = html.unescape(title_m.group(1).strip())
        link   = link_m.group(1).strip()
        source = html.unescape(src_m.group(1).strip()) if src_m else "Unknown"
        desc   = html.unescape(desc_m.group(1).strip())[:300] if desc_m else ""
        desc   = re.sub(r"<[^>]+>", "", desc).strip()
        # Remove trailing " - SourceName" from title
        title  = re.sub(r"\s+[-–|]\s+\S+$", "", title).strip()

        if len(title) < 10:
            continue

        articles.append({"title": title, "link": link, "source": source, "description": desc})

    return articles


# ── article content extraction ───────────────────────────────────

def resolve_article_url(google_news_link: str) -> str | None:
    """Follow Google News redirect to get the real article URL."""
    try:
        req = Request(google_news_link, headers={"User-Agent": UA})
        with urlopen(req, timeout=ARTICLE_TIMEOUT) as resp:
            return resp.geturl()
    except Exception as e:
        print(f"    [resolve WARN] {e}")
        return None


def extract_article_text(html_content: str) -> str:
    """Extract main text from article HTML using simple heuristics."""
    # Remove scripts, styles, nav, header, footer
    for tag in ["script","style","nav","header","footer","aside","noscript",
                "iframe","form","button","figure","figcaption","svg"]:
        html_content = re.sub(
            rf"<{tag}[^>]*>.*?</{tag}>", " ", html_content,
            flags=re.DOTALL | re.IGNORECASE
        )

    # Get all paragraph text
    paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", html_content, re.DOTALL)
    if not paragraphs:
        # fallback: strip all tags
        text = re.sub(r"<[^>]+>", " ", html_content)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:2000]

    lines = []
    total = 0
    for p in paragraphs:
        clean = re.sub(r"<[^>]+>", "", p).strip()
        clean = html.unescape(clean)
        clean = re.sub(r"\s+", " ", clean)
        if len(clean) < 20:  # skip nav/short lines
            continue
        lines.append(clean)
        total += len(clean)
        if total > 3000:
            break

    return "\n\n".join(lines)


def fetch_article_content(google_news_link: str) -> str | None:
    """Resolve link and fetch full article text."""
    real_url = resolve_article_url(google_news_link)
    if not real_url:
        return None

    try:
        req = Request(real_url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        })
        with urlopen(req, timeout=ARTICLE_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        return extract_article_text(raw)
    except Exception as e:
        print(f"    [fetch WARN] {e}")
        return None


# ── translation ──────────────────────────────────────────────────

def translate_to_zh(text: str) -> str:
    """Translate to Chinese via Google Translate API."""
    if not text or len(text.strip()) < 5:
        return text
    # Split long text into chunks for better translation
    chunks = []
    remaining = text.strip()
    while remaining:
        chunk = remaining[:800]
        chunks.append(chunk)
        remaining = remaining[800:]

    results = []
    for chunk in chunks:
        try:
            encoded = quote(chunk, safe="")
            url = (f"https://translate.googleapis.com/translate_a/single"
                   f"?client=gtx&sl=en&tl=zh-CN&dt=t&q={encoded}")
            req = Request(url, headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
                "Referer": "https://translate.google.com/",
            })
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            if data and data[0]:
                translated = "".join(seg[0] for seg in data[0] if seg[0])
                results.append(translated)
            else:
                results.append(chunk)
        except Exception as e:
            print(f"    [TL WARN] {e}")
            results.append(chunk)
        time.sleep(0.2)

    return "".join(results)


# ── scoring & selection ──────────────────────────────────────────

def score_article(article: dict) -> float:
    text = (article["title"] + " " + article["description"]).lower()
    score = len(article.get("description", "")) * 0.01
    for kw in BOOST_KW:
        if kw.lower() in text:
            score += 2.5
    # Boost for articles with substantial descriptions
    if len(article.get("description", "")) > 80:
        score += 1.5
    return score


def deduplicate(articles: list) -> list:
    seen = set()
    out = []
    for a in articles:
        key = a["title"].lower()[:50]
        if key not in seen:
            seen.add(key)
            out.append(a)
    return out


# ── email builder (NO LINKS) ─────────────────────────────────────

def build_email(articles: list) -> str:
    """Build Chinese report email with plain text content, NO links."""
    now = datetime.now(TZ)
    date_str = now.strftime("%Y年%m月%d日")

    sections = []
    for i, a in enumerate(articles, 1):
        title   = a.get("title_zh") or a["title"]
        summary = a.get("summary_zh") or a.get("summary") or ""
        source  = a.get("source", "")
        section = f"""        <tr>
            <td style="padding:22px 18px;border-bottom:1px solid #f0f0f0;">
                <div style="display:flex;align-items:flex-start;gap:12px;">
                    <span style="flex-shrink:0;width:30px;height:30px;line-height:30px;
                                 background:linear-gradient(135deg,#1677ff,#0958d9);
                                 color:#fff;border-radius:8px;text-align:center;
                                 font-size:14px;font-weight:bold;">{i}</span>
                    <div style="flex:1;min-width:0;">
                        <div style="font-size:16px;font-weight:700;color:#1a1a1a;
                                    line-height:1.5;margin-bottom:10px;">{html.escape(title)}</div>"""
        if summary:
            section += f"""
                        <div style="font-size:14px;color:#333;line-height:1.85;
                                    text-align:justify;padding:12px 14px;
                                    background:#f8f9ff;border-radius:8px;
                                    border-left:3px solid #1677ff;">
                            {html.escape(summary)}
                        </div>"""
        section += f"""
                        <div style="margin-top:8px;font-size:12px;color:#999;">
                            📰 来源：{html.escape(source)}</div>
                    </div>
                </div>
            </td>
        </tr>"""
        sections.append(section)

    if not sections:
        sections.append("""        <tr><td style="padding:30px;text-align:center;color:#999;font-size:14px;">
            今日暂未获取到相关新闻，明天再来看看吧。</td></tr>""")

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:16px;background:#f5f6fa;
             font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
    <div style="max-width:680px;margin:0 auto;">
        <div style="background:linear-gradient(135deg,#1677ff 0%,#0958d9 100%);
                    padding:28px 22px;border-radius:14px 14px 0 0;">
            <h1 style="color:#fff;margin:0;font-size:22px;font-weight:700;">
                🤖 AI 领域每日速递</h1>
            <p style="color:rgba(255,255,255,0.85);margin:8px 0 0;font-size:13px;">
                {date_str} · 聚焦 AI Coding 与具身智能 · 中文内容摘要</p>
        </div>
        <table style="width:100%;border-collapse:collapse;background:#fff;
                      border-radius:0 0 14px 14px;
                      box-shadow:0 2px 12px rgba(0,0,0,0.06);">
            <tbody>
{''.join(sections)}
            </tbody>
        </table>
        <p style="color:#aaa;font-size:11px;text-align:center;margin-top:16px;">
            由 GitHub Actions 自动生成 · 每日 08:00（北京时间） · 纯内容不含链接</p>
    </div>
</body></html>"""


# ── email send ───────────────────────────────────────────────────

def send_email(html_content: str):
    msg = MIMEMultipart("alternative")
    now = datetime.now(TZ)
    msg["Subject"] = f"🤖 AI 速递 | {now.strftime('%m/%d')} · AI Coding & 具身智能"
    msg["From"] = QQ_EMAIL
    msg["To"]   = RECIPIENT
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    print(f"  Sending to {RECIPIENT} ...")
    with smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=15) as s:
        s.login(QQ_EMAIL, QQ_SMTP_CODE)
        s.sendmail(QQ_EMAIL, [RECIPIENT], msg.as_string())
    print("  ✓ Email sent!")


# ── main flow ────────────────────────────────────────────────────

def main():
    print("=" * 56)
    print("  Daily AI News Push — Full Content Edition")
    print(f"  {datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')} (Beijing)")
    print("=" * 56)

    # ── Phase 1: Collect candidates ──
    print("\n[1/5] Fetching news headlines from Google News ...")
    all_arts = []
    for query, label in QUERIES:
        print(f"  - {label}")
        arts = fetch_google_news_rss(query)
        for a in arts:
            a["score"] = score_article(a)
        all_arts.extend(arts)
        time.sleep(0.6)

    if not all_arts:
        print("  [FATAL] No articles at all. Sending fallback email.")
        send_email(build_email([]))
        return

    all_arts = deduplicate(all_arts)
    all_arts.sort(key=lambda a: a.get("score", 0), reverse=True)
    candidates = all_arts[:MAX_ARTICLES]
    print(f"  Selected {len(candidates)} candidates from {len(all_arts)} total")

    # ── Phase 2: Fetch full content ──
    print(f"\n[2/5] Fetching full article content ...")
    enriched = []
    for i, art in enumerate(candidates):
        print(f"  [{i+1}/{len(candidates)}] {art['title'][:50]}...")
        content = fetch_article_content(art["link"])
        if content:
            art["summary"] = content[:MAX_SUMMARY_LEN]
            print(f"      → Got {len(content)} chars")
        else:
            # Fallback: use RSS description
            art["summary"] = art.get("description", "")[:300]
            print(f"      → Using RSS description ({len(art['summary'])} chars)")
        enriched.append(art)
        time.sleep(0.5)

    # ── Phase 3: Translate ──
    print(f"\n[3/5] Translating to Chinese ...")
    for i, art in enumerate(enriched):
        prefix = f"  [{i+1}/{len(enriched)}]"
        # Translate title
        print(f"{prefix} TL title: {art['title'][:35]}...")
        art["title_zh"] = translate_to_zh(art["title"])
        time.sleep(0.4)

        # Translate summary
        summary = art.get("summary", "")
        if summary:
            print(f"{prefix} TL summary ({len(summary)} chars)")
            art["summary_zh"] = translate_to_zh(summary)
            time.sleep(0.5)
        else:
            art["summary_zh"] = ""

    # ── Phase 4: Build email ──
    print(f"\n[4/5] Building email ...")
    email_html = build_email(enriched)

    # ── Phase 5: Send ──
    print(f"\n[5/5] Sending ...")
    send_email(email_html)
    print("\n✓ All done!")


if __name__ == "__main__":
    main()
