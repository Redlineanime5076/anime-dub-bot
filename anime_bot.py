import os
import time
import html
import requests
import feedparser

# Telegram Credentials
BOT_TOKEN = "8998736470:AAH1yImwe-hq-IVB1ktG98BRbUt4-gwJ4g"
CHAT_ID = "-1004472229971"

# All Active Anime News RSS Feeds
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
    {"name": "Anime Geek", "url": "https://www.monstersandcritics.com/anime/feed/"}
]

HISTORY_FILE = "sent_posts.txt"

def load_sent_posts():
    if not os.path.exists(HISTORY_FILE):
        return set()
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())

def save_sent_post(post_id):
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(f"{post_id}\n")

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        res_data = response.json()
        if not res_data.get("ok"):
            print(f"Telegram API Error: {res_data}")
            return False
        time.sleep(2.0)  # Rate limit এড়াতে ২ সেকেন্ড বিরতি
        return True
    except Exception as e:
        print(f"Network error: {e}")
        return False

def fetch_feed(url):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        res = requests.get(url, headers=headers, timeout=15)
        res.raise_for_status()
        return feedparser.parse(res.content)
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return feedparser.parse("")

def main():
    sent_posts = load_sent_posts()
    new_posts_found = 0

    for feed_info in RSS_FEEDS:
        source_name = feed_info["name"]
        feed_url = feed_info["url"]

        feed = fetch_feed(feed_url)
        if not feed.entries:
            continue

        for entry in reversed(feed.entries[:2]):
            post_id = entry.get("id") or entry.get("link")
            if not post_id or post_id in sent_posts:
                continue

            raw_title = entry.get("title", "Anime News Update").strip()
            link = entry.get("link", "").strip()
            published = entry.get("published", entry.get("updated", "")).strip()

            # HTML ক্যারেক্টার ক্লিন করা
            safe_title = html.escape(raw_title)
            safe_source = html.escape(source_name)

            caption = (
                f"🔥 <b>[{safe_source}]</b>\n\n"
                f"📢 <b>{safe_title}</b>\n\n"
            )
            if published:
                caption += f"📅 <i>{html.escape(published)}</i>\n"
            caption += f"🔗 <a href='{link}'>Read Full Article</a>"

            if send_telegram_message(caption):
                save_sent_post(post_id)
                sent_posts.add(post_id)
                new_posts_found += 1
                print(f"Posted to Telegram: {raw_title[:30]}")

    if new_posts_found == 0:
        print("No new updates found.")

if __name__ == "__main__":
    main()
