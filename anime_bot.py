import os
import sys
import time
import json
import html
import re
from io import BytesIO
from difflib import SequenceMatcher
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin
from email.utils import parsedate_to_datetime
import requests
import feedparser
from bs4 import BeautifulSoup

CONFIG_FILE = "config.json"

def load_config():
    if not os.path.exists(CONFIG_FILE):
        print(f"Error: {CONFIG_FILE} not found!")
        sys.exit(1)
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

CONFIG = load_config()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = "@databaceforredlineanime"
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID") or CONFIG.get("admin_chat_id", "7154131818")

if not BOT_TOKEN:
    print("Error: BOT_TOKEN not found in GitHub Secrets.")
    sys.exit(1)

DRY_RUN = CONFIG.get("dry_run", False)
POSTS_PER_FEED = CONFIG.get("posts_per_feed", 3)
POSTS_PER_CR = CONFIG.get("posts_per_cr", 25)
MAX_HISTORY_RECORDS = CONFIG.get("max_history_records", 1500)
SIMILARITY_THRESHOLD = CONFIG.get("title_similarity_threshold", 0.72)
BLOCKLIST = [k.lower() for k in CONFIG.get("blocklist_keywords", [])]
DEFAULT_IMAGE_URL = CONFIG.get("default_image_url", "https://i.postimg.cc/NfGqLbCv/1793778285021.png")
CHANNEL_FOOTER = CONFIG.get("channel_footer", "")
RSS_FEEDS = CONFIG.get("rss_feeds", [])
ANIME_TAG_MAP = CONFIG.get("anime_tag_map", {})

HISTORY_FILE = "sent_posts.txt"
RECENT_TITLES_FILE = "recent_titles.txt"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5"
}

CUTOFF_DATE = datetime(2026, 10, 29, 0, 0, 0, tzinfo=timezone.utc)
JP_RE = re.compile(r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]")
API = f"https://api.telegram.org/bot{BOT_TOKEN}"


def send_admin_alert(error_message):
    """সমস্যা হলে অ্যাডমিনকে সরাসরি পার্সোনাল মেসেজ পাঠায়"""
    if not ADMIN_CHAT_ID or DRY_RUN:
        return
    text = f"⚠️ <b>[Anime Bot Alert]</b>\n\n{html.escape(error_message)}"
    try:
        requests.post(f"{API}/sendMessage", json={
            "chat_id": ADMIN_CHAT_ID,
            "text": text,
            "parse_mode": "HTML"
        }, timeout=10)
    except Exception:
        pass


def generate_hashtags(title, source_name=""):
    """টাইটেল ও সোর্স অনুযায়ী প্রয়োজনীয় হ্যাশট্যাগ যোগ করে"""
    tags = set()
    t_lower = title.lower()

    # জনপ্রিয় এনিমে হ্যাশট্যাগ
    for name, tag_str in ANIME_TAG_MAP.items():
        if name in t_lower:
            for t in tag_str.split():
                tags.add(t)

    # ক্যাটাগরি হ্যাশট্যাগ
    if any(k in t_lower for k in ["trailer", "pv", "teaser"]):
        tags.add("#Trailer")
    if any(k in t_lower for k in ["season 2", "s2", "season 3", "s3", "second season", "third season"]):
        tags.add("#NewSeason")
    if any(k in t_lower for k in ["movie", "film"]):
        tags.add("#AnimeMovie")
    if any(k in t_lower for k in ["hindi", "dubbed", "dub"]):
        tags.add("#HindiDub")
    if "Alert" in source_name or "Crunchyroll Latest" in source_name:
        tags.add("#StreamingAlert")
    else:
        tags.add("#AnimeNews")

    return " ".join(sorted(tags))


def clean_summary_text(summary_html):
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
    params = {"client": "gtx", "sl": "ja", "tl": "en", "dt": "t", "q": text}

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


def load_lines(filename):
    if not os.path.exists(filename):
        return []
    with open(filename, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def save_lines_capped(filename, new_item, max_records):
    items = load_lines(filename)
    items.append(new_item)
    if len(items) > max_records:
        items = items[-max_records:]
    with open(filename, "w", encoding="utf-8") as f:
        for item in items:
            f.write(f"{item}\n")


def is_title_duplicate(title, recent_titles):
    clean_t = re.sub(r'[^a-zA-Z0-9\s]', '', title.lower()).strip()
    for prev in recent_titles:
        clean_prev = re.sub(r'[^a-zA-Z0-9\s]', '', prev.lower()).strip()
        sim = SequenceMatcher(None, clean_t, clean_prev).ratio()
        if sim >= SIMILARITY_THRESHOLD:
            return True
    return False


def is_blocked(title):
    t_lower = title.lower()
    return any(word in t_lower for word in BLOCKLIST)


def preflight_check():
    try:
        me = requests.get(f"{API}/getMe", timeout=15).json()
        if not me.get("ok"):
            send_admin_alert("Bot Token Invalid or getMe failed!")
            return False
        chat = requests.get(f"{API}/getChat", params={"chat_id": CHAT_ID}, timeout=15).json()
        if not chat.get("ok", False):
            send_admin_alert(f"Cannot access channel {CHAT_ID}. Ensure bot is an admin.")
            return False
        return True
    except Exception as e:
        send_admin_alert(f"Preflight Exception: {e}")
        return False


def send_telegram_message(message, image_url="", button_url="", button_text="Read Full Article"):
    if DRY_RUN:
        print(f"[DRY_RUN] Message to post:\n{message[:200]}...\nImage: {image_url}\nButton: {button_url}")
        return True

    reply_markup = None
    if button_url and button_url.startswith("http"):
        reply_markup = {
            "inline_keyboard": [
                [{"text": f"🔗 {button_text}", "url": button_url}]
            ]
        }

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
                if reply_markup:
                    data["reply_markup"] = json.dumps(reply_markup)

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
    if reply_markup:
        payload["reply_markup"] = reply_markup

    for _ in range(3):
        try:
            res = requests.post(f"{API}/sendMessage", json=payload, timeout=15)
            if res.json().get("ok"):
                time.sleep(2.5)
                return True
        except Exception:
            time.sleep(3)
    return False


def fetch_feed(url, name=""):
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        if res.status_code == 200:
            return feedparser.parse(res.content)
        elif res.status_code in [403, 404, 500]:
            print(f"Feed error ({res.status_code}) on {name}")
        return feedparser.parse("")
    except Exception as e:
        print(f"Exception fetching {name}: {e}")
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
    elif "media_content" in entry and entry["media_content"]:
        image_url = entry["media_content"][0].get("url", "")
    elif "enclosures" in entry and entry["enclosures"]:
        image_url = entry["enclosures"][0].get("href", "")

    hashtags = generate_hashtags(raw_title, source_name)

    # ১. ক্রাঞ্চিরোল স্ট্রিমিং ও ডাব রিলিজ
    if source_name == "Crunchyroll Latest Releases":
        anime_name, episode, audio, subs = extract_media_details(raw_title, desc)
        msg = (
            "🚨 <b>#STREAMING_ALERT</b> 🚨\n\n"
            f"🎬 <b>Anime: {html.escape(anime_name)}</b>\n"
            f"🔢 <b>Episode: {html.escape(episode)}</b>\n"
            f"🎙 <b>Audio: {html.escape(audio)}</b>\n"
            f"📝 <b>Subtitles: {html.escape(subs)}</b>\n"
            f"📅 <b>Time: {html.escape(published)}</b>\n\n"
            f"🏷 {hashtags}\n"
            f"{CHANNEL_FOOTER}"
        )
        return msg, f"{anime_name} - {episode}", image_url, link, "Watch on Crunchyroll", True

    # ২. OTT স্ট্রিমিং অ্যালার্ট
    if "Alert" in source_name:
        platform_name = source_name.replace(" Anime Alert", "").strip()
        anime_name, episode, audio, subs = extract_media_details(raw_title, desc)
        msg = (
            "🚨 <b>#STREAMING_ALERT</b> 🚨\n\n"
            f"🎬 <b>Anime: {html.escape(anime_name)}</b>\n"
            f"📺 <b>Platform: {html.escape(platform_name)}</b>\n"
            f"🎙 <b>Audio: {html.escape(audio)}</b>\n"
            f"📝 <b>Subtitles: {html.escape(subs)}</b>\n"
            f"📅 <b>Time: {html.escape(published)}</b>\n\n"
            f"🏷 {hashtags}\n"
            f"{CHANNEL_FOOTER}"
        )
        return msg, anime_name, image_url, link, f"Watch on {platform_name}", True

    # ৩. গ্লোবাল ও ভারতীয় অ্যানিমে নিউজ
    translated_title, ok = translate_if_japanese(raw_title)
    key_points = clean_summary_text(desc)

    msg = (
        f"🌍 <b>[{html.escape(source_name)}]</b>\n\n"
        f"📰 <b>Title: {html.escape(translated_title)}</b>\n\n"
    )
    if key_points:
        msg += f"📌 <b>Key Points:</b>\n• <b>{html.escape(key_points)}</b>\n\n"
    if published:
        msg += f"📅 <b>{html.escape(published)}</b>\n\n"

    msg += f"🏷 {hashtags}\n"
    msg += f"{CHANNEL_FOOTER}"

    if not image_url and link:
        image_url = extract_og_image(link)

    return msg, translated_title, image_url, link, "Read Full Article", ok


def main():
    if not preflight_check():
        sys.exit(1)

    sent_posts = set(load_lines(HISTORY_FILE))
    recent_titles = load_lines(RECENT_TITLES_FILE)
    new_posts_found = 0

    # ১. Crunchyroll Live Release Calendar
    cal_releases = fetch_crunchyroll_calendar()
    for rel in cal_releases:
        if rel["id"] in sent_posts:
            continue

        hashtags = generate_hashtags(rel['title'], "Crunchyroll Latest")
        msg = (
            "🚨 <b>#STREAMING_ALERT</b> 🚨\n\n"
            f"🎬 <b>Anime: {html.escape(rel['title'])}</b>\n"
            f"🔢 <b>Episode: {html.escape(rel['episode'])}</b>\n"
            f"🎙 <b>Audio: {html.escape(rel['audio'])}</b>\n"
            "📝 <b>Subtitles: English</b>\n\n"
            f"🏷 {hashtags}\n"
            f"{CHANNEL_FOOTER}"
        )
        if send_telegram_message(msg, rel["image"], rel["link"], "Watch on Crunchyroll"):
            save_lines_capped(HISTORY_FILE, rel["id"], MAX_HISTORY_RECORDS)
            sent_posts.add(rel["id"])
            new_posts_found += 1
            print(f"Posted Calendar: {rel['title']} ({rel['audio']})")

    # ২. সমস্ত আরএসএস ফিডস
    for feed_info in RSS_FEEDS:
        source_name = feed_info["name"]
        feed = fetch_feed(feed_info["url"], source_name)
        if not feed.entries:
            continue

        limit = POSTS_PER_CR if source_name == "Crunchyroll Latest Releases" else POSTS_PER_FEED

        for entry in reversed(feed.entries[:limit]):
            raw_id = entry.get("id") or entry.get("link") or ""
            raw_title = entry.get("title", "").strip()

            post_id = f"{raw_id}::{raw_title}" if any(k in source_name for k in ["Crunchyroll", "Alert"]) else raw_id

            if not post_id or post_id in sent_posts:
                continue

            if is_blocked(raw_title):
                continue

            if not any(k in source_name for k in ["Crunchyroll", "Alert"]):
                if is_title_duplicate(raw_title, recent_titles):
                    print(f"Skipped duplicate news: {raw_title[:40]}...")
                    continue

            entry_dt = get_entry_datetime(entry)
            if entry_dt and entry_dt < CUTOFF_DATE:
                continue

            message, title, image_url, button_url, button_text, ok = build_message(source_name, entry, entry_dt)
            if not ok:
                continue

            if send_telegram_message(message, image_url, button_url, button_text):
                save_lines_capped(HISTORY_FILE, post_id, MAX_HISTORY_RECORDS)
                save_lines_capped(RECENT_TITLES_FILE, raw_title, 200)
                sent_posts.add(post_id)
                recent_titles.append(raw_title)
                new_posts_found += 1
                print(f"Posted: {title[:45]}")

    if new_posts_found == 0:
        print("No new updates found.")
    else:
        print(f"Total {new_posts_found} new posts sent.")


if __name__ == "__main__":
    main()
