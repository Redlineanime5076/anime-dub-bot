import os
import requests
import feedparser

# Telegram Bot Configurations
BOT_TOKEN = "8998736470:AAH1yImwe-hq-IVB1ktG98BRbUt4-gwJ4g"
CHAT_ID = "7154131818"

# RSS Feed URL from MyAnimeList
RSS_URL = "https://myanimelist.net/rss/news.xml"
HISTORY_FILE = "sent_posts.txt"

def load_sent_posts():
    """Load previously sent post IDs/links from history file."""
    if not os.path.exists(HISTORY_FILE):
        return set()
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())

def save_sent_post(post_id):
    """Save newly sent post ID/link to history file."""
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(f"{post_id}\n")

def send_telegram_message(message):
    """Send text message to Telegram chat via Bot API."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    try:
        response = requests.post(url, json=payload, timeout=15)
        response.raise_for_status()
        print("Notification sent successfully.")
    except Exception as e:
        print(f"Error sending message: {e}")

def main():
    sent_posts = load_sent_posts()
    feed = feedparser.parse(RSS_URL)

    if not feed.entries:
        print("No entries found in the RSS feed.")
        return

    # Process items from oldest to newest among the latest entries
    new_entries = []
    for entry in reversed(feed.entries[:10]):
        post_id = entry.get("id", entry.get("link"))
        if post_id not in sent_posts:
            new_entries.append(entry)

    if not new_entries:
        print("No new anime updates found.")
        return

    for entry in new_entries:
        title = entry.get("title", "Anime News Update")
        link = entry.get("link", "")
        published = entry.get("published", "")

        caption = (
            f"📢 <b>{title}</b>\n\n"
            f"📅 Date: {published}\n"
            f"🔗 Read more: {link}"
        )

        send_telegram_message(caption)
        post_id = entry.get("id", entry.get("link"))
        save_sent_post(post_id)

if __name__ == "__main__":
    main()
