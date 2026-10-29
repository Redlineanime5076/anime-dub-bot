import os
import sys
import time
import html
import requests
import feedparser

# GitHub Secrets থেকে টোকেন নেওয়া হচ্ছে
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = "@databaceforredlineanime"

if not BOT_TOKEN:
    print("❌ BOT_TOKEN পাওয়া যায়নি! GitHub Secrets ঠিকভাবে সেট করা হয়েছে কি না দেখুন।")
    sys.exit(1)

POSTS_PER_FEED = 2
HISTORY_FILE = "sent_posts.txt"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

RSS_FEEDS = [
    {"name": "Google News (Anime)", "url": "https://news.google.com/rss/search?q=anime&hl=en-US&gl=US&ceid=US:en"},
    {"name": "MyAnimeList", "url": "https://myanimelist.net/rss/news.xml"},
    {"name": "Anime News Network", "url": "https://www.animenewsnetwork.com/news/rss.xml"},
    {"name": "Crunchyroll News", "url": "https://cr-news-api-service.prd.crunchyrollsvc.com/v1/en-US/rss"},
    {"name": "ComicBook Anime", "url": "https://comicbook.com/anime/rss.xml"},
    {"name": "Otaku USA", "url": "https://otakuusamagazine.com/feed/"},
    {"name": "CBR Anime", "url": "https://www.cbr.com/feed/category/anime/"},
    {"name": "Screen Rant Anime", "url": "https://screenrant.com/feed/category/anime/"},
    {"name": "Game Rant Anime", "url": "https://gamerant.com/feed/category/anime/"},
    {"name": "Siliconera Anime", "url": "https://www.siliconera.com/category/anime/feed/"},
    {"name": "Reddit r/anime News", "url": "https://www.reddit.com/r/anime/search.rss?q=flair%3ANews&restrict_sr=on&sort=new"},
    {"name": "Reddit r/AnimeDubs", "url": "https://www.reddit.com/r/AnimeDubs/.rss"},
    {"name": "Crunchyroll Trailers YouTube", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCGQnWhqcwG23p1eEptmkTzA"},
    {"name": "TOHO Animation YouTube", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UChLQ_5HP9w46RwnkkdP3peQ"},
    {"name": "SoraNews Anime", "url": "https://soranews24.com/category/anime/feed/"},
    {"name": "Anime Geek", "url": "https://www.monstersandcritics.com/anime/feed/"},
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
        print(f"❌ নেটওয়ার্ক সমস্যা: {e}")
        return False
    if not me.get("ok"):
        print(f"❌ টোকেন ভুল বা বাতিল: {me}")
        return False
    bot_id = me["result"]["id"]
    print(f"✅ বট ঠিক আছে: @{me['result']['username']}")

    chat = requests.get(f"{API}/getChat", params={"chat_id": CHAT_ID}, timeout=15).json()
    if not chat.get("ok"):
        print(f"❌ CHAT_ID সমস্যা (চ্যানেল পাচ্ছে না): {chat}")
        return False
    print(f"✅ চ্যানেল পাওয়া গেছে: {chat['result'].get('title')}")

    member = requests.get(
        f"{API}/getChatMember",
        params={"chat_id": CHAT_ID, "user_id": bot_id},
        timeout=15,
    ).json()
    if not member.get("ok"):
        print(f"❌ বটের স্ট্যাটাস চেক করা যায়নি: {member}")
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


def build_message(source_name, entry):
    raw_title = entry.get("title", "Anime News Update").strip()
    link = entry.get("link", "").strip()
    published = (entry.get("published") or entry.get("updated") or "").strip()

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
            print(f"⚠️ কোনো এন্ট্রি নেই: {source_name}")
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
