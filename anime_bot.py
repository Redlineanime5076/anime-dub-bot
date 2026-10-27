import feedparser
import requests
import time
import os
import re

BOT_TOKEN = "8860854294:AAHN0DXvFJaYhsYSf8vw5RoopR5WsjIbP6Y"
RSS_FEED_URL = "https://myanimelist.net/rss/news.xml"
CHAT_ID = "7154131818"  # আপনার টেলিগ্রাম চ্যাট আইডি এখানে বসান

SEEN_FILE = "seen_articles.txt"

def load_seen_articles():
    if not os.path.exists(SEEN_FILE):
        return set()
    with open(SEEN_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())

def save_article_id(article_id):
    with open(SEEN_FILE, "a", encoding="utf-8") as f:
        f.write(article_id + "\n")

def clean_html(raw_html):
    cleanr = re.compile('<.*?>')
    return re.sub(cleanr, '', raw_html)

def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    try:
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        print(f"Error: {e}")

def main():
    seen_articles = load_seen_articles()
    feed = feedparser.parse(RSS_FEED_URL)
    
    new_found = 0

    for entry in reversed(feed.entries):
        entry_id = entry.get("id", entry.get("link"))

        if entry_id not in seen_articles:
            raw_title = entry.get("title", "No Title")
            title = clean_html(raw_title)

            link = entry.get("link", "")
            if "url=" in link:
                try:
                    link = link.split("url=")[1].split("&")[0]
                except IndexError:
                    pass

            raw_snippet = entry.get("summary", "")
            snippet = clean_html(raw_snippet)
            if len(snippet) > 200:
                snippet = snippet[:200] + "..."

            msg = (
                f"🚨 <b>নতুন হিন্দি ডাব আপডেট!</b>\n\n"
                f"📌 <b>{title}</b>\n\n"
                f"📝 <i>{snippet}</i>\n\n"
                f"🔗 <a href='{link}'>বিস্তারিত পড়ুন</a>"
            )
            send_telegram(msg)
            save_article_id(entry_id)
            seen_articles.add(entry_id)
            new_found += 1
            time.sleep(1.5)

    if new_found == 0:
        print("কোনো নতুন আপডেট নেই।")
    else:
        print(f"{new_found}টি নতুন আপডেট পাঠানো হয়েছে।")

if __name__ == "__main__":
    main()
          
