import os
import sys
import time
import html
import re
from io import BytesIO
from datetime import datetime, timezone, timedelta
from urllib.parse import quote, urljoin
from email.utils import parsedate_to_datetime
import requests
import feedparser
from bs4 import BeautifulSoup

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = "@databaceforredlineanime"

if not BOT_TOKEN:
    print("Error: BOT_TOKEN not found in GitHub Secrets.")
    sys.exit(1)

POSTS_PER_FEED = 3
POSTS_PER_CR = 25
POSTS_PER_X = 3
HISTORY_FILE = "sent_posts.txt"

# পার্মানেন্ট ইমেজ লিংক
DEFAULT_IMAGE_URL = "https://i.postimg.cc/NfGqLbCv/1793778285021.png"

# বোল্ড ফুটার
CHANNEL_FOOTER = """
<b>━━━━━━━━━━━━━━━━━━━━━━━━</b>
📢 <b>Channel: @RedLineAnime</b>
💬 <b>Don't miss any update, share with your friends!</b>"""

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5"
}

CUTOFF_DATE = datetime(2026, 10, 29, 0, 0, 0, tzinfo=timezone.utc)
JP_RE = re.compile(r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]")

# এক্স (Twitter) অ্যাকাউন্ট তালিকা
# এখানে আপনার কাঙ্ক্ষিত X ইউজারনেমগুলো যুক্ত করতে পারেন (@ ছাড়া)
X_ACCOUNTS = [
    {"name": "Anime News & Updates (X)", "username": "AIR_News01"},
    {"name": "Crunchyroll (X)", "username": "Crunchyroll"}
]

# Nitter এবং RSSHub-এর পাবলিক ইনস্ট্যান্স তালিকা (ফলব্যাকের জন্য)
NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.privacydev.net",
    "https://nitter.poast.org"
]
RSSHUB_INSTANCES = [
    "https://rsshub.app",
    "https://rsshub.rssforever.com"
]


def clean_summary_text(summary_html):
    """সামারি থেকে HTML ট্যাগ পরিষ্কার করে ১-২ লাইনের Key Points তৈরি করে"""
    if not summary_html:
        return ""
    soup = BeautifulSoup(summary_html, "html.parser")
    text = soup.get_text(separator=" ").strip()
    text = re.sub(r'\s+', ' ', text)
    if len(text) > 220:
        sentences = re.split(r'(?<=[.!?]) +', text)
        result = ""
        for s in sentences:
            if len(result) + len(s) < 220:
                result += " " + s
            else:
                break
        return result.strip() if result else text[:200] + "..."
    return text


def translate_if_japanese(text):
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
            print(f"Translation Error: {e}")
        time.sleep(2)

    return text, False


def gnews(q, lang="en", country="IN"):
    return f"https://news.google.com/rss/search?q={quote(q)}&hl={lang}-{country}&gl={country}&ceid={country}:{lang}"


def gnews_jp(q):
    return f"https://news.google.com/rss/search?q={quote(q)}&hl=ja&gl=JP&ceid=JP:ja"


RSS_FEEDS = [
    # Crunchyroll Official RSS & News
    {"name": "Crunchyroll Latest Releases", "url": "https://www.crunchyroll.com/rss/anime"},
    {"name": "Crunchyroll News", "url": "https://cr-news-api-service.prd.crunchyrollsvc.com/v1/en-US/rss"},

    # OTT Anime Streaming Alerts (India)
    {"name": "Netflix Anime Alert", "url": gnews('anime ("Netflix" OR "Netflix India") (streaming OR release OR added OR episodes)')},
    {"name": "Prime Video Anime Alert", "url": gnews('anime ("Prime Video" OR "Amazon Prime") (streaming OR release OR Hindi OR Tamil OR Telugu)')},
    {"name": "Disney+ Hotstar Anime Alert", "url": gnews('anime ("Disney+ Hotstar" OR "Disney Plus") (streaming OR release OR dubbed OR Hindi)')},
    {"name": "JioCinema Anime Alert", "url": gnews('anime ("JioCinema" OR "Jio Cinema") (streaming OR release OR Hindi OR dubbed)')},

    # Global Anime News
    {"name": "Anime News Network", "url": "https://www.animenewsnetwork.com/news/rss.xml"},
    {"name": "MyAnimeList News", "url": "https://myanimelist.net/rss/news.xml"},
    {"name": "Anime Corner", "url": "https://animecorner.me/feed/"},
    {"name": "Anime Trending", "url": "https://anitrendz.net/news/feed/"},
    {"name": "Comic Natalie (JP)", "url": gnews_jp("site:natalie.mu/comic")},

    # Manga & Adaptations
    {"name": "Manga Adaptation News", "url": gnews('"manga gets anime" OR "gets tv anime"')},
    {"name": "Anime Season Confirmations", "url": gnews('anime "release date" OR "season confirmed"')},
    {"name": "Anime Trailer Released", "url": gnews('anime "official trailer" OR "main trailer" released')},
    {"name": "Anime PV/Teaser", "url": gnews('anime "promotional video" OR "teaser PV"')}
]

API = f"https://api.telegram.org/bot{BOT_TOKEN}"


def extract_og_image(article_url):
    if not article_url or not article_url.startswith("http"):
        return ""
    try:
        res = requests.get(article_url, headers=HEADERS, timeout=10)
        if res.status_code != 200 or "html" not in res.headers.get("Content-Type", "").lower():
            return ""
        soup = BeautifulSoup(res.text, "html.parser")
        meta_tags = [
            {"property": "og:image"},
            {"property": "og:image:secure_url"},
            {"name": "twitter:image"},
            {"name": "twitter:image:src"}
        ]
        for tag in meta_tags:
            elem = soup.find("meta", attrs=tag)
            if elem and elem.get("content"):
                img = elem["content"].strip()
                if "googleusercontent.com" in img or "gstatic.com" in img:
                    continue
                return urljoin(article_url, img)
    except Exception:
        pass
    return ""


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
        if not me.get("ok"):
            return False
        chat = requests.get(f"{API}/getChat", params={"chat_id": CHAT_ID}, timeout=15).json()
        return chat.get("ok", False)
    except Exception:
        return False


def send_telegram_message(message, image_url=""):
    target_image = image_url if image_url else DEFAULT_IMAGE_URL

    if target_image:
        try:
            img_res = requests.get(target_image, headers=HEADERS, timeout=15)
            if img_res.status_code == 200 and len(img_res.content) > 500:
                img_data = BytesIO(img_res.content)
                files = {"photo": ("image.png", img_data, "image/png")}
                data = {
                    "chat_id": CHAT_ID,
                    "caption": message[:1024],
                    "parse_mode": "HTML"
                }
                res = requests.post(f"{API}/sendPhoto", data=data, files=files, timeout=25)
                if res.json().get("ok"):
                    time.sleep(2.5)
                    return True
        except Exception as e:
            print(f"Photo upload error: {e}")

    payload = {
        "chat_id": CHAT_ID,
        "text": message[:4096],
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    for _ in range(3):
        try:
            res = requests.post(f"{API}/sendMessage", json=payload, timeout=15)
            if res.json().get("ok"):
                time.sleep(2.5)
                return True
        except Exception:
            time.sleep(3)
    return False


def fetch_feed(url):
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        if res.status_code == 200:
            return feedparser.parse(res.content)
        return feedparser.parse("")
    except Exception:
        return feedparser.parse("")


def fetch_x_feed(username):
    """Nitter ও RSSHub উভয় মাধ্যমে এক্স (টুইটার) ফিড ফেচ করার ব্যবস্থা"""
    # ১. প্রথমে Nitter ইনস্ট্যান্সগুলো দিয়ে ট্রাই করবে
    for base in NITTER_INSTANCES:
        try:
            url = f"{base}/{username}/rss"
            res = requests.get(url, headers=HEADERS, timeout=10)
            if res.status_code == 200 and "<rss" in res.text:
                feed = feedparser.parse(res.content)
                if feed.entries:
                    return feed
        except Exception:
            pass

    # ২. Nitter ডাউন থাকলে RSSHub দিয়ে ট্রাই করবে
    for base in RSSHUB_INSTANCES:
        try:
            url = f"{base}/twitter/user/{username}"
            res = requests.get(url, headers=HEADERS, timeout=10)
            if res.status_code == 200 and "<rss" in res.text:
                feed = feedparser.parse(res.content)
                if feed.entries:
                    return feed
        except Exception:
            pass

    return feedparser.parse("")


def get_entry_datetime(entry):
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        return datetime(*parsed[:6], tzinfo=timezone.utc)
    raw = entry.get("published") or entry.get("pubDate") or entry.get("updated")
    if raw:
        try:
            dt = parsedate_to_datetime(raw)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass
    return None


def format_to_ist(entry_dt, entry):
    if entry_dt:
        ist_tz = timezone(timedelta(hours=5, minutes=30))
        return entry_dt.astimezone(ist_tz).strftime("%d %b %Y, %I:%M %p IST")
    return (entry.get("published") or entry.get("pubDate") or "").strip()


def parse_language_codes(text):
    """ক্যালেন্ডারের ছোট কোড এবং পুরো নাম শনাক্ত করে"""
    audios = []
    code_map = {
        "HI": "Hindi Dub",
        "TA": "Tamil Dub",
        "TE": "Telugu Dub",
        "BN": "Bengali Dub",
        "EN": "English",
        "JA": "Japanese"
    }

    for code, full_name in [("HINDI", "Hindi Dub"), ("TAMIL", "Tamil Dub"), ("TELUGU", "Telugu Dub"), ("BENGALI", "Bengali Dub")]:
        if re.search(rf'\b{code}\b', text, re.IGNORECASE):
            if full_name not in audios:
                audios.append(full_name)

    for code, full_name in code_map.items():
        if re.search(rf'(?:\b|,|\s){code}(?:\b|,|\s|\+)', text):
            if full_name not in audios:
                audios.append(full_name)

    if not audios:
        audios.append("Japanese (Original)")

    return audios


def extract_media_details(title, desc=""):
    anime_name = title
    episode = "Episode Update"
    subtitles = ["English"]

    full_text = f"{title} {desc}"
    audios = parse_language_codes(full_text)

    clean_title = re.sub(r'(\[[^\]]+\]|\([^)]+\))', '', title).strip()
    if " - " in clean_title:
        parts = clean_title.split(" - ")
        anime_name = parts[0].strip()
        episode = " - ".join(parts[1:]).strip()
    else:
        anime_name = clean_title

    return anime_name, episode, ", ".join(audios), ", ".join(subtitles)


def fetch_crunchyroll_calendar():
    url = "https://www.crunchyroll.com/simulcastcalendar"
    releases = []
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        if res.status_code != 200:
            return releases

        soup = BeautifulSoup(res.text, "html.parser")
        items = soup.find_all("li", class_=re.compile(r"calendar-entry|episode-item"))
        for item in items:
            title_elem = item.find(class_=re.compile(r"title|series-title"))
            if not title_elem:
                continue
            title = title_elem.get_text(strip=True)

            langs_elem = item.find(class_=re.compile(r"languages|audio-language"))
            langs_text = langs_elem.get_text(separator=" ", strip=True) if langs_elem else ""

            ep_elem = item.find(class_=re.compile(r"episode-num|episode-label"))
            ep_text = ep_elem.get_text(strip=True) if ep_elem else "Episode Update"

            link_elem = item.find("a", href=True)
            link = urljoin("https://www.crunchyroll.com", link_elem["href"]) if link_elem else "https://www.crunchyroll.com"

            img_elem = item.find("img")
            img_url = img_elem.get("src") or img_elem.get("data-src", "") if img_elem else ""

            audios = parse_language_codes(f"{title} {langs_text}")

            releases.append({
                "id": f"cr-cal-{title}-{ep_text}",
                "title": title,
                "episode": ep_text,
                "audio": ", ".join(audios),
                "link": link,
                "image": img_url
            })
    except Exception as e:
        print(f"Error fetching CR calendar: {e}")
    return releases


def build_message(source_name, entry, entry_dt):
    raw_title = entry.get("title", "Anime News Update").strip()
    link = entry.get("link", "").strip()
    desc = entry.get("description", "") or entry.get("summary", "")
    published = format_to_ist(entry_dt, entry)

    image_url = ""
    if "media_thumbnail" in entry and entry["media_thumbnail"]:
        image_url = entry["media_thumbnail"][0].get("url", "")
    elif "enclosures" in entry and entry["enclosures"]:
        image_url = entry["enclosures"][0].get("href", "")

    # ১. ক্রাঞ্চিরোল স্ট্রিমিং ও ডাব রিলিজ
    if source_name == "Crunchyroll Latest Releases":
        anime_name, episode, audio, subs = extract_media_details(raw_title, desc)
        msg = (
            "🚨 <b>#STREAMING_ALERT</b> 🚨\n\n"
            f"🎬 <b>Anime Name: {html.escape(anime_name)}</b>\n"
            f"🔢 <b>Episode: {html.escape(episode)}</b>\n"
            f"🎙 <b>Audio Languages: {html.escape(audio)}</b>\n"
            f"📝 <b>Subtitles: {html.escape(subs)}</b>\n"
            f"📅 <b>Time: {html.escape(published)}</b>\n"
            f"🔗 <b>Platform: <a href=\"{html.escape(link, quote=True)}\">Crunchyroll</a></b>\n"
            f"{CHANNEL_FOOTER}"
        )
        return msg, f"{anime_name} - {episode}", image_url, True

    # ২. OTT স্ট্রিমিং অ্যালার্ট
    if "Alert" in source_name:
        platform_name = source_name.replace(" Anime Alert", "").strip()
        anime_name, episode, audio, subs = extract_media_details(raw_title, desc)
        msg = (
            "🚨 <b>#STREAMING_ALERT</b> 🚨\n\n"
            f"🎬 <b>Anime Name: {html.escape(anime_name)}</b>\n"
            f"🎙 <b>Audio Languages: {html.escape(audio)}</b>\n"
            f"📝 <b>Subtitles: {html.escape(subs)}</b>\n"
            f"📅 <b>Time: {html.escape(published)}</b>\n"
            f"🔗 <b>Platform: <a href=\"{html.escape(link, quote=True)}\">{html.escape(platform_name)}</a></b>\n"
            f"{CHANNEL_FOOTER}"
        )
        return msg, anime_name, image_url, True

    # ৩. এক্স (Twitter) পোস্টের জন্য বিশেষ মেসেজ
    if "(X)" in source_name:
        clean_tweet = clean_summary_text(desc or raw_title)
        translated_tweet, _ = translate_if_japanese(clean_tweet)

        # Nitter লিঙ্ক থাকলে আসল x.com লিঙ্কে পরিবর্তন
        real_link = re.sub(r'https?://[^/]+', 'https://x.com', link) if link else ""

        msg = (
            f"🐦 <b>[{html.escape(source_name)}]</b>\n\n"
            f"💬 <b>{html.escape(translated_tweet)}</b>\n\n"
        )
        if published:
            msg += f"📅 <b>{html.escape(published)}</b>\n"
        if real_link:
            msg += f'🔗 <b><a href="{html.escape(real_link, quote=True)}">View on X</a></b>\n'
        msg += f"{CHANNEL_FOOTER}"

        # টুইটে ছবি থাকলে বের করা
        if not image_url and desc:
            soup = BeautifulSoup(desc, "html.parser")
            img_tag = soup.find("img")
            if img_tag and img_tag.get("src"):
                image_url = img_tag["src"]

        return msg, f"{source_name} Post", image_url, True

    # ৪. গ্লোবাল অ্যানিমে নিউজ
    translated_title, ok = translate_if_japanese(raw_title)
    key_points = clean_summary_text(desc)

    msg = (
        f"🌍 <b>[{html.escape(source_name)}]</b>\n\n"
        f"📰 <b>Title: {html.escape(translated_title)}</b>\n\n"
    )
    if key_points:
        msg += f"📌 <b>Key Points:</b>\n• <b>{html.escape(key_points)}</b>\n\n"
    if published:
        msg += f"📅 <b>{html.escape(published)}</b>\n"
    if link:
        msg += f'🔗 <b><a href="{html.escape(link, quote=True)}">Read Full Article</a></b>\n'

    msg += f"{CHANNEL_FOOTER}"

    if not image_url and link:
        image_url = extract_og_image(link)

    return msg, translated_title, image_url, ok


def main():
    if not preflight_check():
        sys.exit(1)

    sent_posts = load_sent_posts()
    new_posts_found = 0

    # ১. Crunchyroll Live Release Calendar
    cal_releases = fetch_crunchyroll_calendar()
    for rel in cal_releases:
        if rel["id"] in sent_posts:
            continue

        msg = (
            "🚨 <b>#STREAMING_ALERT</b> 🚨\n\n"
            f"🎬 <b>Anime Name: {html.escape(rel['title'])}</b>\n"
            f"🔢 <b>Episode: {html.escape(rel['episode'])}</b>\n"
            f"🎙 <b>Audio Languages: {html.escape(rel['audio'])}</b>\n"
            "📝 <b>Subtitles: English</b>\n"
            f"🔗 <b>Platform: <a href=\"{html.escape(rel['link'], quote=True)}\">Crunchyroll</a></b>\n"
            f"{CHANNEL_FOOTER}"
        )
        if send_telegram_message(msg, rel["image"]):
            save_sent_post(rel["id"])
            sent_posts.add(rel["id"])
            new_posts_found += 1
            print(f"Posted Calendar Release: {rel['title']} ({rel['audio']})")

    # ২. এক্স (Twitter) অ্যাকাউন্ট স্ক্র্যাপার (Nitter + RSSHub)
    for x_acc in X_ACCOUNTS:
        feed = fetch_x_feed(x_acc["username"])
        if not feed.entries:
            continue

        for entry in reversed(feed.entries[:POSTS_PER_X]):
            raw_id = entry.get("id") or entry.get("link") or ""
            if not raw_id or raw_id in sent_posts:
                continue

            entry_dt = get_entry_datetime(entry)
            if entry_dt and entry_dt < CUTOFF_DATE:
                continue

            message, title, image_url, ok = build_message(x_acc["name"], entry, entry_dt)
            if not ok:
                continue

            if send_telegram_message(message, image_url):
                save_sent_post(raw_id)
                sent_posts.add(raw_id)
                new_posts_found += 1
                print(f"Posted X Update: {x_acc['name']}")

    # ৩. গ্লোবাল এবং ওটিটি আরএসএস ফিডস
    for feed_info in RSS_FEEDS:
        source_name = feed_info["name"]
        feed = fetch_feed(feed_info["url"])
        if not feed.entries:
            continue

        limit = POSTS_PER_CR if source_name == "Crunchyroll Latest Releases" else POSTS_PER_FEED

        for entry in reversed(feed.entries[:limit]):
            raw_id = entry.get("id") or entry.get("link") or ""
            raw_title = entry.get("title", "").strip()

            post_id = f"{raw_id}::{raw_title}" if any(k in source_name for k in ["Crunchyroll", "Alert"]) else raw_id

            if not post_id or post_id in sent_posts:
                continue

            entry_dt = get_entry_datetime(entry)
            if entry_dt and entry_dt < CUTOFF_DATE:
                continue

            message, title, image_url, ok = build_message(source_name, entry, entry_dt)
            if not ok:
                continue

            if send_telegram_message(message, image_url):
                save_sent_post(post_id)
                sent_posts.add(post_id)
                new_posts_found += 1
                print(f"Posted: {title[:45]}")

    if new_posts_found == 0:
        print("No new updates found.")
    else:
        print(f"Total {new_posts_found} new posts sent.")


if __name__ == "__main__":
    main()
