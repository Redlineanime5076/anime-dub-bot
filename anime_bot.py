import os
import sys
import time
import html
from datetime import datetime, timezone, timedelta
import requests
import feedparser

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = "@databaceforredlineanime"

if not BOT_TOKEN:
    print("❌ BOT_TOKEN পাওয়া যায়নি! GitHub Secrets ঠিকভাবে সেট করা হয়েছে কি না দেখুন।")
    sys.exit(1)

POSTS_PER_FEED = 2
HISTORY_FILE = "sent_posts.txt"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

RSS_FEEDS = [
    # প্রধান অ্যানিমে নিউজ
    {"name": "Anime News Network", "url": "https://www.animenewsnetwork.com/news/rss.xml"},
    {"name": "MyAnimeList News", "url": "https://myanimelist.net/rss/news.xml"},
    {"name": "Crunchyroll News", "url": "https://cr-news-api-service.prd.crunchyrollsvc.com/v1/en-US/rss"},
    {"name": "Otaku USA Magazine", "url": "https://otakuusamagazine.com/feed/"},
    {"name": "Siliconera", "url": "https://www.siliconera.com/category/anime/feed/"},
    {"name": "Anime UK News", "url": "https://animeuknews.net/feed/"},

    # কি-ভিজুয়াল, পোস্টার ও টিজার
    {"name": "Visual & Teaser Updates", "url": "https://news.google.com/rss/search?q=anime+%22key+visual%22+OR+%22teaser+visual%22&hl=en-US&gl=US&ceid=US:en"},
    {"name": "Anime Character Designs", "url": "https://news.google.com/rss/search?q=anime+%22character+visual%22+OR+%22teaser+trailer%22&hl=en-US&gl=US&ceid=US:en"},

    # নতুন মাঙ্গা ও লাইট নভেল অ্যাডাপ্টেশন
    {"name": "Manga Adaptation News", "url": "https://news.google.com/rss/search?q=%22manga+gets+anime%22+OR+%22gets+tv+anime%22&hl=en-US&gl=US&ceid=US:en"},
    {"name": "Light Novel Adaptations", "url": "https://news.google.com/rss/search?q=%22light+novel+gets+anime%22+OR+%22anime+adaptation%22&hl=en-US&gl=US&ceid=US:en"},

    # রিলিজ ডেট ও নতুন সিজন
    {"name": "Anime Season Confirmations", "url": "https://news.google.com/rss/search?q=anime+%22release+date%22+OR+%22season+confirmed%22&hl=en-US&gl=US&ceid=US:en"}
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
        "disable_web_page_preview": False,
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


def format_to_ist(entry):
    published_parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if published_parsed:
        utc_dt = datetime(*published_parsed[:6], tzinfo=timezone.utc)
        ist_tz = timezone(timedelta(hours=5, minutes=30))
        ist_dt = utc_dt.astimezone(ist_tz)
        return ist_dt.strftime("%d %b %Y, %I:%M %p IST")
    return (entry.get("published") or entry.get("updated") or "").strip()


def build_message(source_name, entry):
    raw_title = entry.get("title", "Anime News Update").strip()
    link = entry.get("link", "").strip()
    published = format_to_ist(entry)

    msg = (
        f"🔥 <b>[{html.escape(source_name)}]</b>\n\n"
        f"📢 <b>{html.escape(raw_title)}</b>\n\n"
    )
    if published:
        msg += f"📅 <i>{html.escape(published)}</i>\n"
    if link:
        msg += f'🔗 <a href="{html.escape(link, quote=True)}">Read Full Article</a>'
    return msg, raw_title


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

            message, raw_title = build_message(source_name, entry)
            if send_telegram_message(message):
                save_sent_post(post_id)
                sent_posts.add(post_id)
                new_posts_found += 1
                print(f"✅ Posted: {raw_title[:40]}")

    if new_posts_found == 0:
        print("No new updates found.")
    else:
        print(f"মোট {new_posts_found}টি নতুন পোস্ট পাঠানো হয়েছে।")


if __name__ == "__main__":
    main()
