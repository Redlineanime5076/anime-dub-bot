import os
import sys
import time
import html
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import quote
from email.utils import parsedate_to_datetime
import requests
import feedparser

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = "@databaceforredlineanime"

if not BOT_TOKEN:
    print("Error: BOT_TOKEN not found in GitHub Secrets.")
    sys.exit(1)

# ---------- সেটিংস ----------
ONLY_HINDI = True          # Crunchyroll STREAMING_ALERT শুধু Hindi Dub এর জন্য
POSTS_PER_FEED = 3
POSTS_PER_CR = 25
MAX_POSTS_PER_RUN = 30     # এক রানে সর্বোচ্চ এতগুলো পোস্ট
MAX_AGE_HOURS = 48         # নিউজ ফিডের এর চেয়ে পুরোনো পোস্ট যাবে না
HISTORY_FILE = "sent_posts.txt"
SHOW_LINK_PREVIEW = True

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

JP_RE = re.compile(r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]")
HINDI_RE = re.compile(
    r"\bHindi\b(?:\s*\([^)]*\))?\s*(?:Dub|Audio)\b|\(\s*Hindi\s*\)", re.IGNORECASE
)
TITLE_CLEAN_RE = re.compile(
    r"\s*\([^)]*\b(?:Dub|Audio)\b[^)]*\)|\s*\(\s*Hindi\s*\)", re.IGNORECASE
)

API = f"https://api.telegram.org/bot{BOT_TOKEN}"


# ---------- Helpers ----------
def is_hindi(text):
    return bool(HINDI_RE.search(text or ""))


def split_title(title):
    clean = TITLE_CLEAN_RE.sub("", title).strip()
    if " - " in clean:
        parts = clean.split(" - ")
        return parts[0].strip(), " - ".join(parts[1:]).strip()
    m = re.split(r"\s+(Episode\s+\d+)", clean, flags=re.IGNORECASE)
    if len(m) > 1:
        return m[0].strip(), m[1].strip()
    return clean, "Episode Update"


def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def hindi_key(name, episode):
    num = re.search(r"(\d+)", str(episode))
    return f"cr-hindi::{norm(name)}::{num.group(1) if num else norm(episode)}"


def translate_if_japanese(text):
    if not text or not JP_RE.search(text):
        return text, True
    params = {"client": "gtx", "sl": "ja", "tl": "en", "dt": "t", "q": text}
    for attempt in range(3):
        try:
            res = requests.get(
                "https://translate.googleapis.com/translate_a/single",
                params=params, headers=HEADERS, timeout=12,
            )
            if res.status_code == 200:
                data = res.json()
                out = "".join(p[0] for p in data[0] if p[0])
                if out:
                    return out.strip(), True
        except Exception as e:
            print(f"Translation error (attempt {attempt + 1}): {e}")
        time.sleep(2)
    return text, False


def gnews(q, lang="en", country="US"):
    return (f"https://news.google.com/rss/search?q={quote(q)}"
            f"&hl={lang}-{country}&gl={country}&ceid={country}:{lang}")


def gnews_jp(q):
    return (f"https://news.google.com/rss/search?q={quote(q)}"
            f"&hl=ja&gl=JP&ceid=JP:ja")


RSS_FEEDS = [
    {"name": "Crunchyroll Latest Releases", "url": "https://www.crunchyroll.com/rss/anime"},
    {"name": "Hindi Dub News", "url": gnews('Crunchyroll OR anime "Hindi dub" OR "Hindi dubbed"')},
    {"name": "Anime News Network", "url": "https://www.animenewsnetwork.com/news/rss.xml"},
    {"name": "ANN (All Content)", "url": "https://www.animenewsnetwork.com/all/rss.xml"},
    {"name": "MyAnimeList News", "url": "https://myanimelist.net/rss/news.xml"},
    {"name": "Crunchyroll News", "url": "https://cr-news-api-service.prd.crunchyrollsvc.com/v1/en-US/rss"},
    {"name": "Otaku USA Magazine", "url": "https://otakuusamagazine.com/feed/"},
    {"name": "Siliconera", "url": "https://www.siliconera.com/category/anime/feed/"},
    {"name": "Anime UK News", "url": "https://animeuknews.net/feed/"},
    {"name": "Anime Corner", "url": "https://animecorner.me/feed/"},
    {"name": "Honey's Anime", "url": "https://honeysanime.com/feed/"},
    {"name": "Anime Herald", "url": "https://www.animeherald.com/feed/"},
    {"name": "The Fandom Post", "url": gnews("site:fandompost.com")},
    {"name": "Comic Natalie (JP)", "url": gnews_jp("site:natalie.mu/comic")},
    {"name": "Manga Adaptation News", "url": gnews('"manga gets anime" OR "gets tv anime"')},
    {"name": "Light Novel Adaptations", "url": gnews('"light novel gets anime" OR "anime adaptation"')},
    {"name": "Anime Season Confirmations", "url": gnews('anime "release date" OR "season confirmed"')},
    {"name": "Anime Movie News", "url": gnews('anime film OR "anime movie" announced')},
    {"name": "Anime Cast & Staff", "url": gnews('anime "cast" OR "staff" announced')},
    {"name": "Streaming Anime", "url": gnews('anime Netflix OR Crunchyroll OR "Prime Video" streaming')},
    {"name": "Visual & Teaser Updates", "url": gnews('anime "key visual" OR "teaser visual"')},
    {"name": "Anime Character Designs", "url": gnews('anime "character visual" OR "teaser trailer"')},
    {"name": "Anime Trailer Released", "url": gnews('anime "official trailer" OR "main trailer" released')},
    {"name": "Anime PV/Teaser", "url": gnews('anime "promotional video" OR "teaser PV"')},
    {"name": "Anime Episode Preview", "url": gnews('anime "episode preview" OR "preview images"')},
    {"name": "Anime Opening/Ending", "url": gnews('anime "opening theme" OR "ending theme" MV')},
    {"name": "Anime Box Office Records", "url": gnews('anime "box office" record OR milestone')},
    {"name": "Crunchyroll & Streaming Records", "url": gnews('anime Crunchyroll record OR viewership milestone')},
    {"name": "Anime Weekly Rankings", "url": gnews('anime ranking OR "anime of the week" OR "top anime"')},
    {"name": "JP Author Illustrations", "url": gnews_jp("描き下ろしイラスト アニメ")},
    {"name": "JP Author Congrats Art", "url": gnews_jp("原作者 お祝いイラスト アニメ")},
    {"name": "JP Anime Announcement", "url": gnews_jp("アニメ化決定")},
    {"name": "JP New Visual", "url": gnews_jp("アニメ 新ビジュアル OR ティザービジュアル")},
    {"name": "JP New Season", "url": gnews_jp("アニメ 第2期 OR 続編 制作決定")},
    {"name": "JP Cast Staff", "url": gnews_jp("アニメ キャスト スタッフ 解禁")},
    {"name": "JP Anime Movie", "url": gnews_jp("劇場アニメ 公開決定")},
    {"name": "JP Trailer/PV", "url": gnews_jp("アニメ 本予告 OR PV公開")},
    {"name": "JP Episode Preview", "url": gnews_jp("アニメ 第 先行カット OR あらすじ")},
    {"name": "JP Box Office Records", "url": gnews_jp("劇場アニメ 興行収入 突破")},
    {"name": "JP Ranking Record", "url": gnews_jp("アニメ ランキング 1位 獲得")},
]


# ---------- History ----------
def load_sent_posts():
    if not os.path.exists(HISTORY_FILE):
        return set()
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def save_sent_post(post_id):
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(f"{post_id}\n")


# ---------- Telegram ----------
def preflight_check():
    try:
        me = requests.get(f"{API}/getMe", timeout=15).json()
    except Exception as e:
        print(f"Network Error: {e}")
        return False
    if not me.get("ok"):
        print(f"Token Error: {me}")
        return False
    bot_id = me["result"]["id"]

    chat = requests.get(f"{API}/getChat", params={"chat_id": CHAT_ID}, timeout=15).json()
    if not chat.get("ok"):
        print(f"CHAT_ID Error: {chat}")
        return False

    member = requests.get(
        f"{API}/getChatMember",
        params={"chat_id": CHAT_ID, "user_id": bot_id}, timeout=15,
    ).json()
    if not member.get("ok"):
        print(f"Status Check Failed: {member}")
        return False
    info = member["result"]
    if info.get("status") not in ("administrator", "creator"):
        print("Bot is not an admin in the channel.")
        return False
    if info.get("can_post_messages") is False:
        print("Bot lacks 'Post Messages' permission.")
        return False
    return True


def send_telegram_message(message):
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": not SHOW_LINK_PREVIEW,
    }
    for _ in range(3):
        try:
            data = requests.post(f"{API}/sendMessage", json=payload, timeout=15).json()
        except Exception as e:
            print(f"Network Error: {e}")
            time.sleep(3)
            continue
        if data.get("ok"):
            time.sleep(2.5)
            return True
        if data.get("error_code") == 429:
            wait = data.get("parameters", {}).get("retry_after", 10)
            print(f"Rate limit, waiting {wait}s...")
            time.sleep(wait + 1)
            continue
        print(f"Telegram API Error: {data}")
        return False
    return False


def stream_alert(name, episode, published, link):
    return (
        "🚨 <b>#STREAMING_ALERT</b> 🚨\n\n"
        f"🎬 <b>Anime Name:</b> {html.escape(name)}\n"
        f"🔢 <b>Episode:</b> {html.escape(str(episode))}\n"
        "🎙 <b>Audio:</b> Hindi Dub\n"
        f"📅 <b>Time:</b> <i>{html.escape(published)}</i>\n"
        f'🔗 <b>Platform:</b> <a href="{html.escape(link, quote=True)}">Crunchyroll</a>'
    )


# ---------- Sources ----------
def fetch_feed(url):
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        res.raise_for_status()
        return feedparser.parse(res.content)
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return feedparser.parse("")


def get_entry_datetime(entry):
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        return datetime(*parsed[:6], tzinfo=timezone.utc)
    raw = entry.get("published") or entry.get("pubDate") or entry.get("updated")
    if raw:
        try:
            return parsedate_to_datetime(raw).astimezone(timezone.utc)
        except Exception:
            pass
    return None


def format_to_ist(dt, entry=None):
    if dt:
        ist = timezone(timedelta(hours=5, minutes=30))
        return dt.astimezone(ist).strftime("%d %b %Y, %I:%M %p IST")
    entry = entry or {}
    return (entry.get("published") or entry.get("pubDate") or "").strip()


def fetch_crunchyroll_hindi_calendar():
    """আসল ব্রাউজারে ক্যালেন্ডার খুলে Hindi Dub এন্ট্রি আনে।"""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        print(f"Playwright not installed: {e}")
        return []

    results = []
    now = datetime.now(timezone.utc)
    urls = [
        f"https://www.crunchyroll.com/releasecalendar?date={now.strftime('%Y-%m-%d')}",
        f"https://www.crunchyroll.com/releasecalendar?date={(now - timedelta(days=7)).strftime('%Y-%m-%d')}",
    ]

    js_extract = """
    els => els.map(e => {
        const card = e.closest('article') || e.closest('li') || e.parentElement;
        return {
            href: e.href,
            text: ((e.innerText || '') + ' ' + (e.getAttribute('title') || '') + ' ' +
                   (e.getAttribute('aria-label') || '')).trim(),
            card: card ? (card.innerText || '') : ''
        };
    })
    """

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                locale="en-IN",
                user_agent=BROWSER_UA,
                viewport={"width": 1400, "height": 2200},
            )
            page = ctx.new_page()

            for url in urls:
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(9000)
                    page.mouse.wheel(0, 4000)       # lazy-load এর জন্য স্ক্রল
                    page.wait_for_timeout(3000)
                except Exception as e:
                    print(f"Calendar load error: {e}")
                    continue

                items = page.eval_on_selector_all(
                    "a[href*='/watch/'], a[href*='/series/']", js_extract
                )
                body_text = ""
                try:
                    body_text = page.inner_text("body")
                except Exception:
                    pass

                hindi_items = [i for i in items if is_hindi(i["text"]) or is_hindi(i["card"])]
                print(f"Calendar {url}")
                print(f"  links={len(items)}, hindi_items={len(hindi_items)}, "
                      f"'hindi' in page={len(re.findall('hindi', body_text, re.I))}")
                for s in items[:4]:
                    print("  sample:", s["text"][:90].replace("\n", " | "))
                for m in list(re.finditer("hindi", body_text, re.I))[:3]:
                    ctx_txt = body_text[max(0, m.start() - 50): m.end() + 50]
                    print("  hindi-context:", ctx_txt.replace("\n", " | "))

                for i in hindi_items:
                    src = i["text"] if is_hindi(i["text"]) else i["card"]
                    lines = [l.strip() for l in src.split("\n") if l.strip()]
                    raw_title = next((l for l in lines if is_hindi(l)), lines[0] if lines else "")
                    ep_match = re.search(r"(?:\bE|Episode\s*)(\d+)", src, re.IGNORECASE)
                    raw_ep = f"Episode {ep_match.group(1)}" if ep_match else "Episode Update"
                    name = TITLE_CLEAN_RE.sub("", raw_title).strip()
                    if not name:
                        continue
                    results.append((hindi_key(name, raw_ep), name, raw_ep, i["href"]))

            browser.close()
    except Exception as e:
        print(f"Playwright error: {e}")

    seen, unique = set(), []
    for item in results:
        if item[0] not in seen:
            seen.add(item[0])
            unique.append(item)
    return unique


def build_news_message(source_name, entry, entry_dt):
    """(message, title, ok, hindi_info) রিটার্ন করে।"""
    raw_title = entry.get("title", "Anime News Update").strip()
    link = entry.get("link", "").strip()
    desc = entry.get("description", "")
    published = format_to_ist(entry_dt, entry)

    if source_name == "Crunchyroll Latest Releases":
        if not is_hindi(f"{raw_title} {desc}"):
            return None, raw_title, True, "skip"
        name, episode = split_title(raw_title)
        msg = stream_alert(name, episode, published, link)
        return msg, f"{name} - {episode}", True, (name, episode)

    title, ok = translate_if_japanese(raw_title)
    msg = (
        f"🔥 <b>[{html.escape(source_name)}]</b>\n\n"
        f"📢 <b>{html.escape(title)}</b>\n\n"
    )
    if published:
        msg += f"📅 <i>{html.escape(published)}</i>\n"
    if link:
        msg += f'🔗 <a href="{html.escape(link, quote=True)}">Read Full Article</a>'
    return msg, title, ok, None


# ---------- Main ----------
def main():
    if not preflight_check():
        sys.exit(1)

    sent = load_sent_posts()
    new_count = 0
    min_dt = datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS)

    def mark(pid):
        save_sent_post(pid)
        sent.add(pid)

    def limit_reached():
        return new_count >= MAX_POSTS_PER_RUN

    # 1. Crunchyroll Calendar (Hindi Dub) - আসল ব্রাউজার দিয়ে
    for key, name, episode, link in fetch_crunchyroll_hindi_calendar():
        if limit_reached():
            break
        if key in sent:
            continue
        msg = stream_alert(name, episode, format_to_ist(datetime.now(timezone.utc)), link)
        if send_telegram_message(msg):
            mark(key)
            new_count += 1
            print(f"Hindi Dub (calendar): {name} - {episode}")

    # 2. RSS Feeds
    for feed_info in RSS_FEEDS:
        if limit_reached():
            print("Run limit reached, rest will go next run.")
            break

        source = feed_info["name"]
        feed = fetch_feed(feed_info["url"])
        if not feed.entries:
            print(f"No entries: {source}")
            continue

        limit = POSTS_PER_CR if source == "Crunchyroll Latest Releases" else POSTS_PER_FEED
        for entry in reversed(feed.entries[:limit]):
            if limit_reached():
                break

            raw_id = entry.get("id") or entry.get("link") or ""
            raw_title = entry.get("title", "").strip()
            post_id = f"{raw_id}::{raw_title}" if source == "Crunchyroll Latest Releases" else raw_id
            if not post_id or post_id in sent:
                continue

            entry_dt = get_entry_datetime(entry)
            if entry_dt and entry_dt < min_dt:
                continue

            message, title, ok, hindi = build_news_message(source, entry, entry_dt)

            if hindi == "skip":      # Crunchyroll এন্ট্রি কিন্তু Hindi নয়
                mark(post_id)
                continue
            if not ok:
                print(f"Skipping untranslated: {title[:40]}")
                continue

            hkey = None
            if hindi:
                hkey = hindi_key(hindi[0], hindi[1])
                if hkey in sent:
                    mark(post_id)
                    continue

            if send_telegram_message(message):
                mark(post_id)
                if hkey:
                    mark(hkey)
                new_count += 1
                print(f"Posted: {title[:45]}")

    print("No new updates found." if new_count == 0 else f"Total {new_count} new posts sent.")


if __name__ == "__main__":
    main()
