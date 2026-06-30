#!/usr/bin/env python3
"""
Daily AI News Push – GitHub Actions
Fetches AI news from direct tech media RSS feeds (rich descriptions),
filters by AI coding + embodied intelligence, translates to Chinese,
and sends a pure-content report email (NO links, NO redirect issues).
"""

import os, re, sys, time, json, html
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen
from urllib.parse import quote
import ssl

# ── config ──────────────────────────────────────────────────────
QQ_EMAIL     = os.environ["QQ_EMAIL"]
QQ_SMTP_CODE = os.environ["QQ_SMTP_CODE"]
RECIPIENT    = os.environ.get("RECIPIENT", QQ_EMAIL)
TZ           = timezone(timedelta(hours=8))

# Direct RSS feeds with rich article descriptions
RSS_FEEDS = [
    ("https://techcrunch.com/category/artificial-intelligence/feed/",       "TechCrunch"),
    ("https://venturebeat.com/category/ai/feed/",                           "VentureBeat"),
    ("https://feeds.arstechnica.com/arstechnica/index",                     "Ars Technica"),
    ("https://www.artificialintelligence-news.com/feed/",                   "AI News"),
    ("https://syncedreview.com/feed/",                                      "Synced"),
]

# Also try Google News for discovery (keeps us aware of broader news)
GOOGLE_QUERIES = [
    ("AI coding agent tool 2026",        "AI编程"),
    ("humanoid robot embodied 2026",     "具身智能"),
    ("OpenAI Anthropic Google DeepMind", "AI巨头"),
]

# Keywords for scoring relevance to our focus areas
AI_CODING_KW = [
    "coding agent","code generation","copilot","cursor","claude code",
    "ai developer","code completion","gpt engineer","devin","windsurf",
    "ai programming","code assistant","agentic coding","ai ide",
    "github copilot","code review ai","ai code","codex",
]
EMBODIED_KW = [
    "humanoid robot","embodied intelligence","robot learning",
    "robotics","bipedal","humanoid","agibot","figure ai","tesla bot",
    "optimus","unitree","boston dynamics","embodied ai",
    "dexterous","manipulation","robot hand","locomotion",
]
GENERAL_AI_KW = [
    "gpt","claude","gemini","grok","llama","mistral","deepseek",
    "openai","anthropic","google deepmind","xai",
    "large language model","transformer","foundation model",
    "multi-modal","rag","agent","fine-tun","reinforcement learning",
]

MAX_ARTICLES = 5
FETCH_TIMEOUT = 15
UA = "Mozilla/5.0 (compatible; NewsBot/1.0)"

# ── RSS fetcher ──────────────────────────────────────────────────

def fetch_rss(url: str, source_name: str) -> list:
    """Fetch RSS and extract title + description."""
    req = Request(url, headers={"User-Agent": UA})
    try:
        ctx = ssl.create_default_context()
        with urlopen(req, timeout=FETCH_TIMEOUT, context=ctx) as resp:
            raw = resp.read()
    except Exception as e:
        print(f"  [WARN] {source_name}: {e}")
        return []

    items = re.findall(r"<item>(.*?)</item>", raw.decode("utf-8", errors="replace"), re.DOTALL)
    articles = []
    for item_xml in items:
        title_m = re.search(r"<(?:title|media:title)[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</(?:title|media:title)>", item_xml, re.DOTALL)
        desc_m  = re.search(r"<(?:description|content:encoded|media:description)[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</(?:description|content:encoded|media:description)>", item_xml, re.DOTALL)
        link_m  = re.search(r"<link[^>]*>(.*?)</link>", item_xml)
        # Some feeds use <link href="..."/> or atom:link
        if not link_m:
            link_m = re.search(r'<link[^>]+href=["\']([^"\']+)["\']', item_xml)

        if not title_m:
            continue

        title = html.unescape(title_m.group(1).strip())
        # Remove trailing source suffix
        title = re.sub(r"\s+[-–|]\s+\S+$", "", title).strip()

        desc = ""
        if desc_m:
            desc = html.unescape(desc_m.group(1).strip())
            # Strip HTML tags
            desc = re.sub(r"<li>", "\n• ", desc)
            desc = re.sub(r"<br\s*/?>", "\n", desc)
            desc = re.sub(r"<[^>]+>", " ", desc)
            desc = re.sub(r"&[a-z]+;", " ", desc)
            # Collapse whitespace
            desc = re.sub(r"\s+", " ", desc).strip()
            # Remove common junk patterns
            desc = re.sub(r"©\s*\d{4}.*$", "", desc)
            desc = re.sub(r"Read more\s*\.?$", "", desc, flags=re.IGNORECASE)
            desc = re.sub(r"The post .*? appeared first on .*?\.?$", "", desc, flags=re.IGNORECASE)
            desc = desc.strip()

        if len(title) < 10:
            continue

        articles.append({
            "title": title,
            "description": desc[:800],
            "source": source_name,
        })

    return articles


# ── scoring ──────────────────────────────────────────────────────

def score_article(art: dict) -> float:
    """Score relevance to AI coding + embodied intelligence."""
    text = f"{art['title']} {art.get('description','')}".lower()
    score = 0.0

    # Base score from description length
    desc_len = len(art.get("description", ""))
    score += min(desc_len / 50.0, 6.0)  # up to 6pts for long descriptions

    # AI Coding keywords
    for kw in AI_CODING_KW:
        if kw.lower() in text:
            score += 4.0
            break  # one match per category is enough

    # Embodied intelligence keywords
    for kw in EMBODIED_KW:
        if kw.lower() in text:
            score += 4.0
            break

    # General AI keywords
    match_count = 0
    for kw in GENERAL_AI_KW:
        if kw.lower() in text:
            match_count += 1
    score += min(match_count, 4) * 1.5  # up to 6pts

    # Bonus for title mentioning our focus areas
    title_lower = art["title"].lower()
    for kw in ["coding","programming","code","developer","agent"]:
        if kw in title_lower:
            score += 2.0
            break
    for kw in ["robot","humanoid","embodied","bipedal"]:
        if kw in title_lower:
            score += 2.0
            break

    return score


def deduplicate(articles: list) -> list:
    seen = set()
    out = []
    for a in articles:
        key = re.sub(r"[^\w]", "", a["title"].lower())[:40]
        if key and key not in seen:
            seen.add(key)
            out.append(a)
    return out


# ── translation ──────────────────────────────────────────────────

def translate_to_zh(text: str) -> str:
    """Translate to Chinese via Google Translate."""
    if not text or len(text.strip()) < 5:
        return text

    chunks = []
    remaining = text.strip()
    while remaining:
        chunks.append(remaining[:800])
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
            ctx = ssl.create_default_context()
            with urlopen(req, timeout=10, context=ctx) as resp:
                data = json.loads(resp.read().decode())
            if data and data[0]:
                translated = "".join(seg[0] for seg in data[0] if seg[0])
                results.append(translated)
            else:
                results.append(chunk)
        except Exception as e:
            print(f"    [TL WARN] {e}")
            results.append(chunk)
        time.sleep(0.15)

    return "".join(results)


# ── email builder (NO LINKS, pure content) ───────────────────────

def build_email(articles: list) -> str:
    now = datetime.now(TZ)
    date_str = now.strftime("%Y年%m月%d日")

    sections = []
    for i, a in enumerate(articles, 1):
        title   = a.get("title_zh") or a["title"]
        summary = a.get("summary_zh") or a.get("description", "")
        source  = a.get("source", "")

        # Clean up summary: remove sentences that are just boilerplate
        summary = re.sub(r"©\s*\d{4}.*$", "", summary)
        summary = summary.strip()

        section = f"""        <tr>
            <td style="padding:22px 18px;border-bottom:1px solid #f0f0f0;">
                <div style="display:flex;align-items:flex-start;gap:12px;">
                    <span style="flex-shrink:0;width:30px;height:30px;line-height:30px;
                                 background:linear-gradient(135deg,#1677ff,#0958d9);
                                 color:#fff;border-radius:8px;text-align:center;
                                 font-size:14px;font-weight:bold;">{i}</span>
                    <div style="flex:1;min-width:0;">
                        <div style="font-size:16px;font-weight:700;color:#1a1a1a;
                                    line-height:1.5;margin-bottom:10px;">
                            {html.escape(title)}</div>"""
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
        sections.append("""        <tr><td style="padding:30px;text-align:center;
            color:#999;font-size:14px;">
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
                {date_str} · 聚焦 AI Coding 与具身智能 · 纯内容无外链</p>
        </div>
        <table style="width:100%;border-collapse:collapse;background:#fff;
                      border-radius:0 0 14px 14px;
                      box-shadow:0 2px 12px rgba(0,0,0,0.06);">
            <tbody>
{''.join(sections)}
            </tbody>
        </table>
        <p style="color:#aaa;font-size:11px;text-align:center;margin-top:16px;">
            由 GitHub Actions 自动生成 · 每日 08:00（北京时间）</p>
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


# ── main ─────────────────────────────────────────────────────────

def main():
    print("=" * 56)
    print("  Daily AI News Push — Direct RSS Edition")
    print(f"  {datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')} (Beijing)")
    print("=" * 56)

    # ── Phase 1: Collect from direct RSS feeds ──
    print("\n[1/4] Fetching from direct RSS feeds ...")
    all_arts = []
    for feed_url, name in RSS_FEEDS:
        print(f"  - {name}: {feed_url[:50]}...")
        arts = fetch_rss(feed_url, name)
        for a in arts:
            a["score"] = score_article(a)
        all_arts.extend(arts)
        print(f"    → {len(arts)} articles")
        time.sleep(0.5)

    total_pre_dedup = len(all_arts)
    all_arts = deduplicate(all_arts)
    all_arts.sort(key=lambda a: a.get("score", 0), reverse=True)

    # Top candidates
    candidates = []
    for a in all_arts:
        if a["score"] > 3.0:  # minimum relevance threshold
            candidates.append(a)
        if len(candidates) >= MAX_ARTICLES:
            break

    if not candidates:
        print("  No relevant articles found. Using top scored ones.")
        candidates = all_arts[:MAX_ARTICLES]

    print(f"  Selected {len(candidates)} from {total_pre_dedup} total ({len(all_arts)} unique)")
    for c in candidates:
        print(f"    [{c['source']}] score={c['score']:.1f} | {c['title'][:55]}")

    # ── Phase 2: Translate ──
    print(f"\n[2/4] Translating to Chinese ...")
    for i, art in enumerate(candidates):
        prefix = f"  [{i+1}/{len(candidates)}]"

        print(f"{prefix} Title: {art['title'][:40]}...")
        art["title_zh"] = translate_to_zh(art["title"])
        time.sleep(0.3)

        desc = art.get("description", "")
        if desc and len(desc) > 30:
            # Take first ~400 chars of description for translation
            summary_text = desc[:450]
            print(f"{prefix} Summary ({len(summary_text)} chars)")
            art["summary_zh"] = translate_to_zh(summary_text)
            time.sleep(0.5)
        else:
            art["summary_zh"] = ""

    # ── Phase 3: Build email ──
    print(f"\n[3/4] Building email ...")
    email_html = build_email(candidates)

    # ── Phase 4: Send ──
    print(f"\n[4/4] Sending ...")
    send_email(email_html)
    print("\n✓ All done!")


if __name__ == "__main__":
    main()
