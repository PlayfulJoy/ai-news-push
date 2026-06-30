#!/usr/bin/env python3
"""
Daily AI News Push – GitHub Actions v5
More tech sources, 8 articles, ~300-char Chinese summaries from full article text.
NO links in email, pure readable content.
"""

import os, re, sys, time, json, html
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen
from urllib.parse import quote, urlparse
import ssl

# ── config ──────────────────────────────────────────────────────
QQ_EMAIL     = os.environ["QQ_EMAIL"]
QQ_SMTP_CODE = os.environ["QQ_SMTP_CODE"]
RECIPIENT    = os.environ.get("RECIPIENT", QQ_EMAIL)
TZ           = timezone(timedelta(hours=8))

# Broad tech + AI RSS feeds with rich content
RSS_FEEDS = [
    # AI-focused
    ("https://techcrunch.com/category/artificial-intelligence/feed/",       "TechCrunch AI"),
    ("https://venturebeat.com/category/ai/feed/",                           "VentureBeat AI"),
    ("https://www.artificialintelligence-news.com/feed/",                   "AI News"),
    ("https://syncedreview.com/feed/",                                      "Synced Review"),
    # General tech (often covers AI)
    ("https://techcrunch.com/feed/",                                        "TechCrunch"),
    ("https://www.theverge.com/rss/index.xml",                              "The Verge"),
    ("https://feeds.arstechnica.com/arstechnica/index",                     "Ars Technica"),
    ("https://www.wired.com/feed/rss",                                      "Wired"),
    ("https://rss.slashdot.org/Slashdot/slashdotMain",                      "Slashdot"),
    ("https://feeds.feedburner.com/oreilly/radar",                          "O'Reilly Radar"),
    # Robotics / hardware
    ("https://spectrum.ieee.org/robotics/feed",                             "IEEE Robotics"),
    ("https://spectrum.ieee.org/ai/feed",                                   "IEEE AI"),
    # Hacker News top stories (JSON)
    ("https://hacker-news.firebaseio.com/v0/topstories.json",               "Hacker News"),
]

# Keywords for scoring
AI_CODING_KW = [
    "coding agent","code generation","copilot","cursor","claude code",
    "ai developer","code completion","gpt engineer","devin","windsurf",
    "ai programming","code assistant","agentic coding","ai ide",
    "github copilot","code review ai","ai code","codex","ai coding",
    "software development ai","programming assistant",
]
EMBODIED_KW = [
    "humanoid robot","embodied intelligence","robot learning",
    "robotics","bipedal","humanoid","agibot","figure ai","tesla bot",
    "optimus","unitree","boston dynamics","embodied ai",
    "dexterous","manipulation","robot hand","locomotion",
    "servo","actuator","sim-to-real",
]
GENERAL_AI_KW = [
    "gpt","claude","gemini","grok","llama","mistral","deepseek",
    "openai","anthropic","google deepmind","xai","meta ai",
    "large language model","transformer","foundation model",
    "multi-modal","rag","agent","fine-tun","reinforcement learning",
    "neural network","machine learning","artificial intelligence",
    "chatbot","llm","reasoning model","agi",
]
TECH_KW = [
    "chip","semiconductor","nvidia","gpu","tpu","quantum computing",
    "self-driving","autonomous vehicle","ev","battery",
    "cloud computing","serverless","edge computing",
    "startup","funding","acquisition","ipo","venture capital",
    "regulation","policy","privacy","cybersecurity",
    "open source","linux","kubernetes","docker",
]

MAX_ARTICLES = 8
FETCH_TIMEOUT = 20
ARTICLE_FETCH_TIMEOUT = 12
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0"
TARGET_SUMMARY_CHARS = 600  # ~300 Chinese chars after translation

# ── RSS / JSON fetcher ──────────────────────────────────────────

def fetch_rss(url: str, source_name: str) -> list:
    """Fetch RSS and extract title + description + link."""
    req = Request(url, headers={"User-Agent": UA})
    try:
        ctx = ssl.create_default_context()
        with urlopen(req, timeout=FETCH_TIMEOUT, context=ctx) as resp:
            raw = resp.read()
    except Exception as e:
        print(f"  [WARN] {source_name}: {e}")
        return []

    # Check if this is JSON (Hacker News)
    if "firebaseio.com" in url:
        return fetch_hn_json(raw, source_name)

    items = re.findall(r"<entry.*?>.*?</entry>|<item>(.*?)</item>",
                       raw.decode("utf-8", errors="replace"), re.DOTALL)
    articles = []
    for item_xml in items:
        title_m = re.search(
            r"<(?:title|media:title)[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</(?:title|media:title)>",
            item_xml, re.DOTALL)
        desc_m = re.search(
            r"<(?:description|content:encoded|summary|media:description)[^>]*>"
            r"(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?"
            r"</(?:description|content:encoded|summary|media:description)>",
            item_xml, re.DOTALL)
        link_m = re.search(r"<link[^>]*>(.*?)</link>", item_xml)
        if not link_m:
            link_m = re.search(r'<link[^>]+href=["\']([^"\']+)["\']', item_xml)

        if not title_m:
            continue

        title = html.unescape(title_m.group(1).strip())
        title = re.sub(r"\s+[-–|]\s+\S+$", "", title).strip()

        desc = ""
        if desc_m:
            desc = html.unescape(desc_m.group(1).strip())
            desc = re.sub(r"<li>", "\n• ", desc)
            desc = re.sub(r"<br\s*/?>", "\n", desc)
            desc = re.sub(r"<[^>]+>", " ", desc)
            desc = re.sub(r"&[a-z]+;", " ", desc)
            desc = re.sub(r"\s+", " ", desc).strip()
            desc = re.sub(r"©\s*\d{4}.*$", "", desc)
            desc = re.sub(r"Read more\s*\.?$", "", desc, flags=re.IGNORECASE)
            desc = re.sub(r"The post .*? appeared first on .*?\.?$", "", desc, flags=re.IGNORECASE)
            desc = desc.strip()

        link = ""
        if link_m:
            link = link_m.group(1).strip()

        if len(title) < 10:
            continue

        articles.append({
            "title": title,
            "description": desc[:1200],
            "source": source_name,
            "link": link,
        })

    return articles


def fetch_hn_json(raw: bytes, source_name: str) -> list:
    """Fetch top Hacker News stories via JSON API."""
    try:
        story_ids = json.loads(raw.decode())[:30]  # top 30
    except:
        return []

    articles = []
    for sid in story_ids[:15]:
        try:
            req = Request(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json",
                          headers={"User-Agent": UA})
            ctx = ssl.create_default_context()
            with urlopen(req, timeout=8, context=ctx) as resp:
                story = json.loads(resp.read().decode())
            if story.get("type") == "story" and story.get("title"):
                articles.append({
                    "title": story["title"],
                    "description": "",
                    "source": source_name,
                    "link": story.get("url", ""),
                    "score": story.get("score", 0),
                })
        except:
            pass

    return articles


# ── article content fetcher ────────────────────────────────────

def fetch_article_text(url: str) -> str:
    """Fetch the article page and extract main text content."""
    if not url or len(url) < 10:
        return ""

    # Skip known problematic domains
    skip_domains = ["youtube.com", "twitter.com", "x.com", "tiktok.com",
                    "reddit.com", "facebook.com", "instagram.com"]
    domain = urlparse(url).netloc.lower()
    if any(d in domain for d in skip_domains):
        return ""

    try:
        req = Request(url, headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml",
        })
        ctx = ssl.create_default_context()
        with urlopen(req, timeout=ARTICLE_FETCH_TIMEOUT, context=ctx) as resp:
            html_raw = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"    [fetch WARN] {url[:40]}: {e}")
        return ""

    # Extract article content using heuristic HTML parsing
    # Strategy: find the largest text block in article-like containers
    text = extract_main_text(html_raw)
    return text


def extract_main_text(html_raw: str) -> str:
    """Heuristic extraction of main article text from HTML."""
    # Remove scripts, styles, nav, header, footer, sidebar
    html_raw = re.sub(r"<script[^>]*>.*?</script>", "", html_raw, flags=re.DOTALL)
    html_raw = re.sub(r"<style[^>]*>.*?</style>", "", html_raw, flags=re.DOTALL)
    html_raw = re.sub(r"<(?:nav|header|footer|aside|sidebar)[^>]*>.*?</(?:nav|header|footer|aside|sidebar)>",
                      "", html_raw, flags=re.DOTALL)

    # Try to find article body containers
    # Look for <article>, <main>, or divs with article-like class names
    article_blocks = []

    # <article> tag
    for m in re.finditer(r"<article[^>]*>(.*?)</article>", html_raw, re.DOTALL):
        article_blocks.append(m.group(1))

    # <main> tag
    for m in re.finditer(r"<main[^>]*>(.*?)</main>", html_raw, re.DOTALL):
        article_blocks.append(m.group(1))

    # Divs with article/story/post content class
    for m in re.finditer(
        r'<div[^>]+class=["\'][^"\']*(?:article|story|post|entry|content|body|text)[^"\']*["\'][^>]*>'
        r'(.*?)</div>',
        html_raw, re.DOTALL):
        article_blocks.append(m.group(1))

    # If no article containers found, use the whole body
    if not article_blocks:
        body_m = re.search(r"<body[^>]*>(.*?)</body>", html_raw, re.DOTALL)
        if body_m:
            article_blocks.append(body_m.group(1))

    # Extract text from <p> tags in the article blocks
    all_paragraphs = []
    for block in article_blocks:
        paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", block, re.DOTALL)
        for p in paragraphs:
            p = re.sub(r"<[^>]+>", " ", p)  # strip inline HTML
            p = html.unescape(p)
            p = re.sub(r"\s+", " ", p).strip()
            if len(p) > 30:  # skip short/boilerplate paragraphs
                all_paragraphs.append(p)

    # Sort by length and take the longest meaningful ones
    all_paragraphs.sort(key=len, reverse=True)

    # Take enough paragraphs to reach our target summary length
    result_parts = []
    total_len = 0
    for p in all_paragraphs[:12]:  # max 12 paragraphs
        result_parts.append(p)
        total_len += len(p)
        if total_len >= TARGET_SUMMARY_CHARS:
            break

    return " ".join(result_parts)[:TARGET_SUMMARY_CHARS + 200]


# ── scoring ──────────────────────────────────────────────────────

def score_article(art: dict) -> float:
    """Score relevance to AI coding + embodied intelligence + tech."""
    text = f"{art['title']} {art.get('description','')}".lower()
    score = 0.0

    # Description length bonus (longer = more informative)
    desc_len = len(art.get("description", ""))
    score += min(desc_len / 60.0, 5.0)

    # AI Coding keywords (highest priority)
    for kw in AI_CODING_KW:
        if kw.lower() in text:
            score += 5.0
            break

    # Embodied intelligence keywords
    for kw in EMBODIED_KW:
        if kw.lower() in text:
            score += 5.0
            break

    # General AI keywords
    ai_match = 0
    for kw in GENERAL_AI_KW:
        if kw.lower() in text:
            ai_match += 1
    score += min(ai_match, 4) * 1.5

    # Tech keywords (secondary relevance)
    tech_match = 0
    for kw in TECH_KW:
        if kw.lower() in text:
            tech_match += 1
    score += min(tech_match, 3) * 1.0

    # Title bonus for focus areas
    title_lower = art["title"].lower()
    for kw in ["coding","programming","code","developer","agent","copilot","cursor"]:
        if kw in title_lower:
            score += 3.0
            break
    for kw in ["robot","humanoid","embodied","bipedal","optimus","tesla bot"]:
        if kw in title_lower:
            score += 3.0
            break
    for kw in ["openai","anthropic","google deepmind","gpt","claude","gemini"]:
        if kw in title_lower:
            score += 2.0
            break

    # HN score bonus
    hn_score = art.get("score", 0)
    if isinstance(hn_score, (int, float)) and hn_score > 0:
        score += min(hn_score / 50.0, 4.0)

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
    """Translate to Chinese via Google Translate API."""
    if not text or len(text.strip()) < 5:
        return text

    # Split into chunks (Google Translate limit ~800 chars per request)
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
            with urlopen(req, timeout=12, context=ctx) as resp:
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


# ── email builder (NO LINKS, pure content) ───────────────────────

def build_email(articles: list) -> str:
    now = datetime.now(TZ)
    date_str = now.strftime("%Y年%m月%d日")
    count = len(articles)

    sections = []
    for i, a in enumerate(articles, 1):
        title   = a.get("title_zh") or a["title"]
        summary = a.get("summary_zh") or a.get("description", "")
        source  = a.get("source", "")

        # Clean up summary
        summary = re.sub(r"©\s*\d{4}.*$", "", summary)
        summary = summary.strip()

        # Truncate to ~300 Chinese characters if too long
        if len(summary) > 450:
            summary = summary[:420] + "……"

        title_esc = html.escape(title)
        source_esc = html.escape(source)
        summary_esc = html.escape(summary) if summary else ""

        sec = (
            '<tr><td style="padding:22px 18px;border-bottom:1px solid #f0f0f0;">'
            '<div style="display:flex;align-items:flex-start;gap:12px;">'
            '<span style="flex-shrink:0;width:30px;height:30px;line-height:30px;'
            'background:linear-gradient(135deg,#1677ff,#0958d9);'
            'color:#fff;border-radius:8px;text-align:center;'
            'font-size:14px;font-weight:bold;">' + str(i) + '</span>'
            '<div style="flex:1;min-width:0;">'
            '<div style="font-size:16px;font-weight:700;color:#1a1a1a;'
            'line-height:1.5;margin-bottom:10px;">' + title_esc + '</div>'
        )
        if summary:
            sec += (
                '<div style="font-size:14px;color:#333;line-height:1.85;'
                'text-align:justify;padding:12px 14px;'
                'background:#f8f9ff;border-radius:8px;'
                'border-left:3px solid #1677ff;">'
                + summary_esc + '</div>'
            )
        sec += (
            '<div style="margin-top:8px;font-size:12px;color:#999;">'
            + '📰 来源：' + source_esc + '</div>'
            '</div></div></td></tr>'
        )
        sections.append(sec)

    if not sections:
        sections.append(
            '<tr><td style="padding:30px;text-align:center;color:#999;font-size:14px;">'
            '今日暂未获取到相关新闻，明天再来看看吧。</td></tr>'
        )

    sections_html = "".join(sections)

    email = (
        '<!DOCTYPE html>'
        '<html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"></head>'
        '<body style="margin:0;padding:16px;background:#f5f6fa;'
        'font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;">'
        '<div style="max-width:680px;margin:0 auto;">'
        '<div style="background:linear-gradient(135deg,#1677ff 0%,#0958d9 100%);'
        'padding:28px 22px;border-radius:14px 14px 0 0;">'
        '<h1 style="color:#fff;margin:0;font-size:22px;font-weight:700;">'
        '🤖 AI & 科技领域每日速递</h1>'
        '<p style="color:rgba(255,255,255,0.85);margin:8px 0 0;font-size:13px;">'
        + date_str + ' · 聚焦 AI Coding / 具身智能 / 科技前沿 · 纯内容无外链</p>'
        '</div>'
        '<table style="width:100%;border-collapse:collapse;background:#fff;'
        'border-radius:0 0 14px 14px;box-shadow:0 2px 12px rgba(0,0,0,0.06);">'
        '<tbody>' + sections_html + '</tbody></table>'
        '<p style="color:#aaa;font-size:11px;text-align:center;margin-top:16px;">'
        '由 GitHub Actions 自动生成 · 每日 08:00（北京时间）· 共 ' + str(count) + ' 条</p>'
        '</div></body></html>'
    )
    return email


# ── email send ───────────────────────────────────────────────────

def send_email(html_content: str):
    msg = MIMultipart("alternative")
    now = datetime.now(TZ)
    msg["Subject"] = f"🤖 AI & 科技速递 | {now.strftime('%m/%d')} · {MAX_ARTICLES}条精选"
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
    print("  Daily AI & Tech News Push v5")
    print(f"  {datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')} (Beijing)")
    print("=" * 56)

    # ── Phase 1: Collect from all sources ──
    print("\n[1/5] Fetching RSS feeds ...")
    all_arts = []
    for feed_url, name in RSS_FEEDS:
        print(f"  → {name}")
        arts = fetch_rss(feed_url, name)
        for a in arts:
            a["score"] = score_article(a)
        all_arts.extend(arts)
        print(f"    got {len(arts)} articles")
        time.sleep(0.3)

    total_pre = len(all_arts)
    all_arts = deduplicate(all_arts)
    all_arts.sort(key=lambda a: a.get("score", 0), reverse=True)

    # Select top candidates with minimum relevance
    candidates = []
    for a in all_arts:
        if a["score"] >= 3.0:
            candidates.append(a)
        if len(candidates) >= MAX_ARTICLES:
            break

    # If not enough, lower threshold
    if len(candidates) < MAX_ARTICLES:
        for a in all_arts:
            if a not in candidates and a["score"] >= 1.0:
                candidates.append(a)
            if len(candidates) >= MAX_ARTICLES:
                break

    # If still not enough, take top scored regardless
    if len(candidates) < MAX_ARTICLES:
        for a in all_arts:
            if a not in candidates:
                candidates.append(a)
            if len(candidates) >= MAX_ARTICLES:
                break

    print(f"\n  Selected {len(candidates)} / {total_pre} total ({len(all_arts)} unique)")
    for c in candidates:
        desc_len = len(c.get("description", ""))
        print(f"    [{c['source']}] score={c['score']:.1f} desc={desc_len} | {c['title'][:50]}")

    # ── Phase 2: Fetch full article text for longer summaries ──
    print(f"\n[2/5] Fetching full article content ...")
    for i, art in enumerate(candidates):
        link = art.get("link", "")
        desc = art.get("description", "")
        desc_len = len(desc)

        # If RSS description is already long enough (>400 chars), skip article fetch
        if desc_len >= 400:
            print(f"  [{i+1}] RSS desc sufficient ({desc_len} chars), skip fetch")
            art["full_text"] = desc[:TARGET_SUMMARY_CHARS + 100]
            continue

        # Try fetching full article
        if link:
            print(f"  [{i+1}] Fetching {link[:50]}...")
            full_text = fetch_article_text(link)
            if full_text and len(full_text) > desc_len:
                print(f"      → got {len(full_text)} chars from article page")
                art["full_text"] = full_text[:TARGET_SUMMARY_CHARS + 100]
            else:
                print(f"      → no usable content, using RSS desc ({desc_len} chars)")
                art["full_text"] = desc[:TARGET_SUMMARY_CHARS + 100]
        else:
            art["full_text"] = desc[:TARGET_SUMMARY_CHARS + 100]
        time.sleep(0.3)

    # ── Phase 3: Translate ──
    print(f"\n[3/5] Translating to Chinese ...")
    for i, art in enumerate(candidates):
        prefix = f"  [{i+1}/{len(candidates)}]"

        # Translate title
        print(f"{prefix} Title: {art['title'][:40]}...")
        art["title_zh"] = translate_to_zh(art["title"])
        time.sleep(0.3)

        # Translate full text / summary
        full_text = art.get("full_text", art.get("description", ""))
        if full_text and len(full_text) > 30:
            # Take up to ~600 chars (translates to ~300 Chinese chars)
            summary_en = full_text[:TARGET_SUMMARY_CHARS]
            print(f"{prefix} Summary ({len(summary_en)} chars → translating)")
            art["summary_zh"] = translate_to_zh(summary_en)
            time.sleep(0.5)
        else:
            art["summary_zh"] = translate_to_zh(full_text) if full_text else ""

    # ── Phase 4: Build email ──
    print(f"\n[4/5] Building email ...")
    email_html = build_email(candidates)

    # ── Phase 5: Send ──
    print(f"\n[5/5] Sending ...")
    send_email(email_html)
    print("\n✓ All done!")


if __name__ == "__main__":
    main()
