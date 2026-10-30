import os
import sys
import time
import html
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import quote
import requests
import feedparser

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = "@databaceforredlineanime"

if not BOT_TOKEN:
    print("❌ BOT_TOKEN পাওয়া যায়নি! GitHub Secrets ঠিকভাবে সেট করা হয়েছে কি না দেখুন।")
    sys.exit(1)

POSTS_PER_FEED = 2
HISTORY_FILE = "sent_posts.txt"

# লিংকের প্রিভিউ কার্ড অন রাখতে True
SHOW_LINK_PREVIEW = True

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# ২৯ অক্টোবরের পূর্বের পোস্ট ফিল্টার করার ডেট (UTC)
CUTOFF_DATE = datetime(2026, 10, 29, 0, 0, 0, tzinfo=timezone.utc)

JP_RE = re.compile(r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]")


def translate_if_japanese(text):
    """গুগলের ডিরেক্ট এপিআই দিয়ে জাপানি শিরোনাম শতভাগ নির্ভুলভাবে ইংরেজিতে রূপান্তর করে"""
    if not text or not JP_RE.search(text):
        return text, True

    api_url = "https://translate.googleapis.com/translate_a/single"
    params = {
        "client": "gtx",
        "sl": "ja",
        "tl": "en",
        "dt": "t",
        "q": text
    }

    for attempt in range(3):
        try:
            res = requests.get(api_url, params=params, headers=HEADERS, timeout=12)
            if res.status_code == 200:
                data = res.json()
                translated_text = "".join([part[0] for part in data[0] if part[0]])
                if translated_text:
                    return translated_text.strip(), True
        except Exception as e:
            print(f"Translation API Error (attempt {attempt + 1}): {e}")
        time.sleep(2)

    return text, False


def gnews(q, lang="en", country="US"):
    return f"https://news.google.com/rss/search?q={quote(q)}&hl={lang}-{country}&gl={country}&ceid={country}:{lang}"


def gnews_jp(q):
    return f"https://news.google.com/rss/search?q={quote(q)}&hl=ja&gl=JP&ceid=JP:ja"


RSS_FEEDS = [
    # প্রধান গ্লোবাল অ্যানিমে নিউজ পোর্টাল
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
    {"name": "The Fandom Post", "url": "https://www.fandompost.com/feed/"},
    {"name": "Anime Trending", "url": "https://anitrendz.com/news/feed"},

    # জাপানি অফিশিয়াল মিডিয়া পোর্টাল
    {"name": "Comic Natalie (JP)", "url": "https://natalie.mu/comic/feed/news"},

    # মাঙ্গা ও লাইট নভেল অ্যাডাপ্টেশন
    {"name": "Manga Adaptation News", "url": gnews('"manga gets anime" OR "gets tv anime"')},
    {"name": "Light Novel Adaptations", "url": gnews('"light novel gets anime" OR "anime adaptation"')},

    # অ্যানিমে সিজন, মুভি, কাস্ট ও স্ট্রিমিং ঘোষণা
    {"name": "Anime Season Confirmations", "url": gnews('anime "release date" OR "season confirmed"')},
    {"name": "Anime Movie News", "url": gnews('anime film OR "anime movie" announced')},
    {"name": "Anime Cast & Staff", "url": gnews('anime "cast" OR "staff" announced')},
    {"name": "Streaming Anime", "url": gnews('anime Netflix OR Crunchyroll OR "Prime Video" streaming')},

    # কি-ভিজুয়াল, ট্রেলার ও টিজার
    {"name": "Visual & Teaser Updates", "url": gnews('anime "key visual" OR "teaser visual"')},
    {"name": "Anime Character Designs", "url": gnews('anime "character visual" OR "teaser trailer"')},
    {"name": "Anime Trailer Released", "url": gnews('anime "official trailer" OR "main trailer" released')},
    {"name": "Anime PV/Teaser", "url": gnews('anime "promotional video" OR "teaser PV"')},

    # এপিসোড প্রিভিউ, ইমেজ ও থিম সং (OP/ED)
    {"name": "Anime Episode Preview", "url": gnews('anime "episode preview" OR "preview images"')},
    {"name": "Anime Opening/Ending", "url": gnews('anime "opening theme" OR "ending theme" MV')},

    # ভিউজ, বক্স অফিস, চার্ট ও র‍্যাংকিং রেকর্ড
    {"name": "Anime Box Office Records", "url": gnews('anime "box office" record OR milestone')},
    {"name": "Crunchyroll & Streaming Records", "url": gnews('anime Crunchyroll record OR viewership milestone')},
    {"name": "Anime Weekly Rankings", "url": gnews('anime ranking OR "anime of the week" OR "top anime"')},

    # জাপানি ব্রেকিং নিউজ, ইলাস্ট্রেশন ও প্রিভিউ
    {"name": "JP Author Illustrations", "url": gnews_jp("描き下ろしイラスト アニメ")},
    {"name": "JP Author Congrats Art", "url": gnews_jp("原作者 お祝いイラスト アニメ")},
    {"name": "JP Anime Announcement", "url": gnews_jp("アニメ化決定")},
    {"name": "JP New Visual", "url": gnews_jp("アニメ 新ビジュアル OR ティザービジュアル")},
    {"name": "JP New Season", "url": gnews_jp("アニメ 第2期 OR 続編 制作決定")},
    {"name": "JP Cast Staff", "url": gnews_jp("アニメ キャスト スタッフ 解禁")},
    {"name": "JP Anime Movie", "url": gnews_jp("劇場アニメ 公開決定")},
    {"name": "JP Trailer/PV", "url": gnews_jp("アニメ 本予告 OR PV公開")},
    {"name": "JP Episode Preview (先行カット)", "url": gnews_jp("アニメ 第 先行カット OR あらすじ")},
    {"name": "JP Box Office Records", "url": gnews_jp("劇場アニメ 興行収入 突破")},
    {"name": "JP Ranking Record", "url": gnews_jp("アニメ ランキング 1位 獲得")}
]

API = f"https://api.telegram.org/bot{BOT_TOKEN}"


def load_sent_posts():
    if not os.path.exists(HISTORY_FILE):
        return set()
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def save_sent_post(post_id):
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(f"{post_id}\n")


def preflight_check():
    try:
        me = requests.get(f"{API}/getMe", timeout=15).json()
    except Exception as e:
        print(f"❌ Network Error: {e}")
        return False
    if not me.get("ok"):
        print(f"❌ Token Error: {me}")
        return False
    bot_id = me["result"]["id"]
    print(f"✅ বট ঠিক আছে: @{me['result']['username']}")

    chat = requests.get(f"{API}/getChat", params={"chat_id": CHAT_ID}, timeout=15).json()
    if not chat.get("ok"):
        print(f"❌ CHAT_ID সমস্যা: {chat}")
        return False
    print(f"✅ চ্যানেল পাওয়া গেছে: {chat['result'].get('title')}")

    member = requests.get(
        f"{API}/getChatMember",
        params={"chat_id": CHAT_ID, "user_id": bot_id},
        timeout=15,
    ).json()
    if not member.get("ok"):
        print(f"❌ Status Check Failed: {member}")
        return False
    info = member["result"]
    if info.get("status") not in ("administrator", "creator"):
        print("❌ বট চ্যানেলের অ্যাডমিন নয়। অ্যাডমিন বানান।")
        return False
    if info.get("can_post_messages") is False:
        print("❌ বটের 'Post Messages' পারমিশন নেই।")
        return False
    print("✅ বট অ্যাডমিন এবং পোস্ট করতে পারবে।")
    return True


def send_telegram_message(message):
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": not SHOW_LINK_PREVIEW,
    }
    for attempt in range(3):
        try:
            res = requests.post(f"{API}/sendMessage", json=payload, timeout=15)
            data = res.json()
        except Exception as e:
            print(f"Network error: {e}")
            time.sleep(3)
            continue

        if data.get("ok"):
            time.sleep(3)
            return True

        if data.get("error_code") == 429:
            wait = data.get("parameters", {}).get("retry_after", 10)
            print(f"Rate limit, {wait} সেকেন্ড অপেক্ষা...")
            time.sleep(wait + 1)
            continue

        print(f"Telegram API Error: {data}")
        return False
    return False


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
    return None


def format_to_ist(entry_dt, entry):
    if entry_dt:
        ist_tz = timezone(timedelta(hours=5, minutes=30))
        ist_dt = entry_dt.astimezone(ist_tz)
        return ist_dt.strftime("%d %b %Y, %I:%M %p IST")
    return (entry.get("published") or entry.get("updated") or "").strip()


def build_message(source_name, entry, entry_dt):
    raw_title = entry.get("title", "Anime News Update").strip()
    link = entry.get("link", "").strip()
    published = format_to_ist(entry_dt, entry)

    # গুগলের ডিরেক্ট এপিআই দিয়ে ট্রান্সলেট হচ্ছে
    translated_title, ok = translate_if_japanese(raw_title)

    msg = (
        f"🔥 <b>[{html.escape(source_name)}]</b>\n\n"
        f"📢 <b>{html.escape(translated_title)}</b>\n\n"
    )
    if published:
        msg += f"📅 <i>{html.escape(published)}</i>\n"
    if link:
        msg += f'🔗 <a href="{html.escape(link, quote=True)}">Read Full Article</a>'
    return msg, translated_title, ok


def main():
    if not preflight_check():
        sys.exit(1)

    sent_posts = load_sent_posts()
    new_posts_found = 0

    for feed_info in RSS_FEEDS:
        source_name = feed_info["name"]
        feed = fetch_feed(feed_info["url"])
        if not feed.entries:
            continue

        for entry in reversed(feed.entries[:POSTS_PER_FEED]):
            post_id = entry.get("id") or entry.get("link")
            if not post_id or post_id in sent_posts:
                continue

            entry_dt = get_entry_datetime(entry)
            # ২৯ অক্টোবরের আগের পোস্ট ড্রপ হবে
            if entry_dt and entry_dt < CUTOFF_DATE:
                continue

            message, title, ok = build_message(source_name, entry, entry_dt)

            # কোনো কারণে ট্রান্সলেশন ব্যর্থ হলে কাঁচা জাপানি পোস্ট হবে না
            if not ok:
                print(f"⚠️ অনুবাদ হয়নি, পোস্ট ড্রপ করা হলো: {title[:40]}")
                continue

            if send_telegram_message(message):
                save_sent_post(post_id)
                sent_posts.add(post_id)
                new_posts_found += 1
                print(f"✅ Posted: {title[:40]}")

    if new_posts_found == 0:
        print("No new updates found.")
    else:
        print(f"মোট {new_posts_found}টি নতুন পোস্ট পাঠানো হয়েছে।")


if __name__ == "__main__":
    main()
