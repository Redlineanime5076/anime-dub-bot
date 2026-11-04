import os
import sys
import time
import html
import re
import json
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
HISTORY_FILE = "sent_posts.txt"
ANILIST_HOURS = 8

# নির্ভরযোগ্য ডিফল্ট ব্যানার ইমেজ (Imgur CDN)
DEFAULT_IMAGE_URL = "https://i.imgur.com/xdr9fNn.png"

# সম্পূর্ণ বোল্ড করা চ্যানেল ফুটার
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

COMMUNITY_CHANNELS = [
    {"name": "Muse India", "handle": "MuseIndia"},
    {"name": "Ani-One India", "handle": "AniOneIndia"},
    {"name": "Crunchyroll India", "handle": "CrunchyrollIndia"}
]


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
            print(f"Translation API Error (attempt {attempt + 1}): {e}")
        time.sleep(2)

    return text, False


def gnews(q, lang="en", country="IN"):
    return f"https://news.google.com/rss/search?q={quote(q)}&hl={lang}-{country}&gl={country}&ceid={country}:{lang}"


def gnews_jp(q):
    return f"https://news.google.com/rss/search?q={quote(q)}&hl=ja&gl=JP&ceid=JP:ja"


# সঠিক ইউটিউব চ্যানেল আইডি সহ আরএসএস ফিডস
RSS_FEEDS = [
    # Official YouTube Streaming Channels
    {"name": "Ani-One India", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCv0r_aXN3Xz0IeBnrq_K7Lw"},
    {"name": "Ani-One Asia", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UC0wNSTMWIL3qaorLx0jie6A"},
    {"name": "Muse India", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UC5_TXXi1a_mK_YJm6y5U6_w"},
    {"name": "Muse Asia", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCGbsPEJY7rB87Uv3_uB_pCw"},
    {"name": "Crunchyroll India YouTube", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UC1dpwMXjjPe87utZQRrEr3Q"},

    # Crunchyroll Official RSS & News
    {"name": "Crunchyroll Latest Releases", "url": "https://www.crunchyroll.com/rss/anime"},
    {"name": "Crunchyroll News", "url": "https://cr-news-api-service.prd.crunchyrollsvc.com/v1/en-US/rss"},

    # OTT Anime Streaming Alerts (India)
    {"name": "Netflix Anime Alert", "url": gnews('anime ("Netflix" OR "Netflix India") (streaming OR release OR added OR episodes)')},
    {"name": "Prime Video Anime Alert", "url": gnews('anime ("Prime Video" OR "Amazon Prime") (streaming OR release OR Hindi OR Tamil OR Telugu)')},
    {"name": "Disney+ Hotstar Anime Alert", "url": gnews('anime ("Disney+ Hotstar" OR "Disney Plus") (streaming OR release OR dubbed OR Hindi)')},
    {"name": "JioCinema Anime Alert", "url": gnews('anime ("JioCinema" OR "Jio Cinema") (streaming OR release OR Hindi OR dubbed)')},

    # Global Anime News Portals
    {"name": "Anime News Network", "url": "https://www.animenewsnetwork.com/news/rss.xml"},
    {"name": "ANN (All Content)", "url": "https://www.animenewsnetwork.com/all/rss.xml"},
    {"name": "MyAnimeList News", "url": "https://myanimelist.net/rss/news.xml"},
    {"name": "Otaku USA Magazine", "url": "https://otakuusamagazine.com/feed/"},
    {"name": "Siliconera", "url": "https://www.siliconera.com/category/anime/feed/"},
    {"name": "Anime UK News", "url": "https://animeuknews.net/feed/"},
    {"name": "Anime Corner", "url": "https://animecorner.me/feed/"},
    {"name": "Honey's Anime", "url": "https://honeysanime.com/feed/"},
    {"name": "Anime Herald", "url": "https://www.animeherald.com/feed/"},
    {"name": "The Fandom Post", "url": gnews("site:fandompost.com")},
    {"name": "Anime Trending", "url": "https://anitrendz.net/news/feed/"},
    {"name": "Comic Natalie (JP)", "url": gnews_jp("site:natalie.mu/comic")},

    # Manga & Adaptations
    {"name": "Manga Adaptation News", "url": gnews('"manga gets anime" OR "gets tv anime"')},
    {"name": "Light Novel Adaptations", "url": gnews('"light novel gets anime" OR "anime adaptation"')},

    # Industry Confirmations
    {"name": "Anime Season Confirmations", "url": gnews('anime "release date" OR "season confirmed"')},
    {"name": "Anime Movie News", "url": gnews('anime film OR "anime movie" announced')},
    {"name": "Anime Cast & Staff", "url": gnews('anime "cast" OR "staff" announced')},

    # Visuals, Teasers & PVs
    {"name": "Visual & Teaser Updates", "url": gnews('anime "key visual" OR "teaser visual"')},
    {"name": "Anime Character Designs", "url": gnews('anime "character visual" OR "teaser trailer"')},
    {"name": "Anime Trailer Released", "url": gnews('anime "official trailer" OR "main trailer" released')},
    {"name": "Anime PV/Teaser", "url": gnews('anime "promotional video" OR "teaser PV"')},
    {"name": "Anime Episode Preview", "url": gnews('anime "episode preview" OR "preview images"')},
    {"name": "Anime Opening/Ending", "url": gnews('anime "opening theme" OR "ending theme" MV')},

    # Box Office & Records
    {"name": "Anime Box Office Records", "url": gnews('anime "box office" record OR milestone')},
    {"name": "Crunchyroll & Streaming Records", "url": gnews('anime Crunchyroll record OR viewership milestone')},
    {"name": "Anime Weekly Rankings", "url": gnews('anime ranking OR "anime of the week" OR "top anime"')},

    # Japanese Media Announcements
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

ANILIST_URL = "https://graphql.anilist.co"
ANILIST_QUERY = """
query ($from: Int, $to: Int, $page: Int) {
  Page(page: $page, perPage: 50) {
    pageInfo { hasNextPage }
    airingSchedules(airingAt_greater: $from, airingAt_lesser: $to, sort: TIME) {
      episode
      airingAt
      media {
        id
        title { romaji english }
        coverImage { extraLarge large }
        externalLinks { site url }
      }
    }
  }
}
"""


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


def fetch_youtube_community_posts(channel_name, handle):
    url = f"https://www.youtube.com/@{handle}/community"
    posts = []
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        if res.status_code != 200:
            return posts

        match = re.search(r'var ytInitialData = ({.*?});</script>', res.text)
        if not match:
            return posts

        data = json.loads(match.group(1))
        tabs = data.get("contents", {}).get("twoColumnBrowseResultsRenderer", {}).get("tabs", [])
        
        community_tab = None
        for t in tabs:
            tab_renderer = t.get("tabRenderer", {})
            if "community" in tab_renderer.get("title", "").lower():
                community_tab = tab_renderer
                break
        
        if not community_tab:
            return posts

        contents = community_tab.get("content", {}).get("sectionListRenderer", {}).get("contents", [])
        for section in contents:
            item_section = section.get("itemSectionRenderer", {}).get("contents", [])
            for item in item_section:
                post_renderer = item.get("backstagePostThreadRenderer", {}).get("post", {}).get("backstagePostRenderer", {})
                if not post_renderer:
                    continue

                post_id = post_renderer.get("postId", "")
                text_runs = post_renderer.get("contentText", {}).get("runs", [])
                post_text = "".join(r.get("text", "") for r in text_runs).strip()

                image_url = ""
                attachments = post_renderer.get("backstageAttachment", {})
                if "backstageImageRenderer" in attachments:
                    thumbnails = attachments["backstageImageRenderer"].get("image", {}).get("thumbnails", [])
                    if thumbnails:
                        image_url = thumbnails[-1].get("url", "")
                elif "postMultiImageRenderer" in attachments:
                    images = attachments["postMultiImageRenderer"].get("images", [])
                    if images:
                        thumbnails = images[0].get("backstageImageRenderer", {}).get("image", {}).get("thumbnails", [])
                        if thumbnails:
                            image_url = thumbnails[-1].get("url", "")

                post_url = f"https://www.youtube.com/post/{post_id}"
                posts.append({
                    "id": f"yt-comm-{post_id}",
                    "channel": channel_name,
                    "text": post_text,
                    "image": image_url,
                    "url": post_url
                })
    except Exception as e:
        print(f"Error fetching community posts for {channel_name}: {e}")
    return posts[:3]


def fetch_anilist_releases(hours=ANILIST_HOURS):
    now = int(time.time())
    time_from = now - hours * 3600
    results = []

    for page in range(1, 4):
        try:
            res = requests.post(
                ANILIST_URL,
                json={
                    "query": ANILIST_QUERY,
                    "variables": {"from": time_from, "to": now, "page": page},
                },
                headers=HEADERS,
                timeout=15,
            )
            data = res.json().get("data", {}).get("Page", {})
        except Exception as e:
            print(f"AniList Error: {e}")
            break

        if not data or "airingSchedules" not in data:
            break

        for item in data["airingSchedules"]:
            media = item["media"]
            link = next(
                (l["url"] for l in (media.get("externalLinks") or [])
                 if l.get("site") == "Crunchyroll"),
                None,
            )
            if not link:
                continue
            title = media["title"].get("english") or media["title"].get("romaji") or "Unknown"
            image = media.get("coverImage", {}).get("extraLarge") or media.get("coverImage", {}).get("large") or ""
            post_id = f"anilist-{media['id']}-{item['episode']}"
            results.append((post_id, title, item["episode"], item["airingAt"], link, image))

        if not data.get("pageInfo", {}).get("hasNextPage"):
            break
        time.sleep(1)

    return results


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
        params={"chat_id": CHAT_ID, "user_id": bot_id},
        timeout=15,
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


def send_telegram_message(message, image_url=""):
    """ছবি পাইথনের মেমরিতে ডাউনলোড করে সরাসরি আপলোড করে, যাতে টেলিগ্রাম ব্লকেজ না হয়"""
    target_image = image_url if image_url else DEFAULT_IMAGE_URL

    if target_image:
        try:
            # পাইথন সরাসরি ইমেজ ডাউনলোড করে নিচ্ছে
            img_res = requests.get(target_image, headers=HEADERS, timeout=12)
            if img_res.status_code == 200 and len(img_res.content) > 1000:
                img_data = BytesIO(img_res.content)
                files = {"photo": ("image.jpg", img_data, "image/jpeg")}
                data = {
                    "chat_id": CHAT_ID,
                    "caption": message[:1024],
                    "parse_mode": "HTML"
                }
                res = requests.post(f"{API}/sendPhoto", data=data, files=files, timeout=25)
                if res.json().get("ok"):
                    time.sleep(2.5)
                    return True
                else:
                    print(f"Photo send error: {res.json().get('description')}")
        except Exception as e:
            print(f"Exception downloading/uploading photo: {e}")

    # ছবি না পাওয়া গেলে বা ফেইল করলে টেক্সট মেসেজ
    payload = {
        "chat_id": CHAT_ID,
        "text": message[:4096],
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    for attempt in range(3):
        try:
            res = requests.post(f"{API}/sendMessage", json=payload, timeout=15)
            data = res.json()
            if data.get("ok"):
                time.sleep(2.5)
                return True
            if data.get("error_code") == 429:
                wait = data.get("parameters", {}).get("retry_after", 10)
                time.sleep(wait + 1)
                continue
            return False
        except Exception:
            time.sleep(3)
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
        ist_dt = entry_dt.astimezone(ist_tz)
        return ist_dt.strftime("%d %b %Y, %I:%M %p IST")
    return (entry.get("published") or entry.get("pubDate") or "").strip()


def extract_media_details(title, desc=""):
    anime_name = title
    episode = "Episode Update"
    audios = []
    subtitles = ["English"]

    full_text = f"{title} {desc}"

    target_langs = ["Hindi", "Tamil", "Telugu", "Bengali", "Malayalam", "Kannada", "English", "Japanese"]
    for lang in target_langs:
        pattern = rf'\b{lang}\b'
        if re.search(pattern, full_text, re.IGNORECASE):
            label = f"{lang.title()} Dub" if lang.lower() != "japanese" else "Japanese"
            if label not in audios:
                audios.append(label)

    bracket_match = re.findall(r'\(([^)]+Dub|[^)]+Audio)\)', title, re.IGNORECASE)
    for b in bracket_match:
        b_clean = b.strip().title()
        if b_clean not in audios:
            audios.append(b_clean)

    if not audios:
        audios.append("Japanese")

    clean_title = re.sub(r'(\[[^\]]+\]|\([^)]+\))', '', title).strip()

    if " - " in clean_title:
        parts = clean_title.split(" - ")
        anime_name = parts[0].strip()
        episode = " - ".join(parts[1:]).strip()
    elif " Episode " in clean_title:
        parts = re.split(r'\s+(Episode\s+\d+)', clean_title, flags=re.IGNORECASE)
        anime_name = parts[0].strip()
        episode = parts[1].strip() if len(parts) > 1 else "Episode"
    else:
        anime_name = clean_title

    if re.search(r'\b(bengali|bangla)\b', full_text, re.IGNORECASE):
        if "Bengali" not in subtitles:
            subtitles.append("Bengali")

    return anime_name, episode, ", ".join(audios), ", ".join(subtitles)


def build_message(source_name, entry, entry_dt):
    raw_title = entry.get("title", "Anime News Update").strip()
    link = entry.get("link", "").strip()
    desc = entry.get("description", "")
    published = format_to_ist(entry_dt, entry)

    image_url = ""
    if "media_thumbnail" in entry and entry["media_thumbnail"]:
        image_url = entry["media_thumbnail"][0].get("url", "")
    elif "enclosures" in entry and entry["enclosures"]:
        image_url = entry["enclosures"][0].get("href", "")

    # 1. Crunchyroll Releases
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

    # 2. Ani-One, Muse & Crunchyroll India YouTube
    if any(k in source_name for k in ["Ani-One", "Muse", "YouTube"]):
        anime_name, episode, audio, subs = extract_media_details(raw_title, desc)
        platform_name = source_name.replace(" Releases", "")
        msg = (
            "🚨 <b>#STREAMING_ALERT</b> 🚨\n\n"
            f"🎬 <b>Anime Name: {html.escape(anime_name)}</b>\n"
            f"🔢 <b>Episode: {html.escape(episode)}</b>\n"
            f"🎙 <b>Audio Languages: {html.escape(audio)}</b>\n"
            f"📝 <b>Subtitles: {html.escape(subs)}</b>\n"
            f"📅 <b>Time: {html.escape(published)}</b>\n"
            f"🔗 <b>Platform: <a href=\"{html.escape(link, quote=True)}\">YouTube ({html.escape(platform_name)})</a></b>\n"
            f"{CHANNEL_FOOTER}"
        )
        return msg, f"{anime_name} - {episode}", image_url, True

    # 3. OTT Streaming Alerts
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

    # 4. News Articles
    translated_title, ok = translate_if_japanese(raw_title)

    msg = (
        f"🔥 <b>[{html.escape(source_name)}]</b>\n\n"
        f"📢 <b>{html.escape(translated_title)}</b>\n\n"
    )
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

    # 1. YouTube Community Posts
    for ch in COMMUNITY_CHANNELS:
        posts = fetch_youtube_community_posts(ch["name"], ch["handle"])
        for p in posts:
            if p["id"] in sent_posts:
                continue
            
            clean_text = p["text"]
            if len(clean_text) > 400:
                clean_text = clean_text[:400] + "..."

            msg = (
                f"📢 <b>[YouTube Community Post - {html.escape(p['channel'])}]</b>\n\n"
                f"<b>{html.escape(clean_text)}</b>\n\n"
                f'🔗 <b><a href="{html.escape(p["url"], quote=True)}">View Community Post</a></b>\n'
                f"{CHANNEL_FOOTER}"
            )
            if send_telegram_message(msg, p["image"]):
                save_sent_post(p["id"])
                sent_posts.add(p["id"])
                new_posts_found += 1
                print(f"Posted Community Update: {p['channel']}")

    # 2. Global & Regional RSS Feeds
    for feed_info in RSS_FEEDS:
        source_name = feed_info["name"]
        feed = fetch_feed(feed_info["url"])
        if not feed.entries:
            continue

        limit = POSTS_PER_CR if source_name == "Crunchyroll Latest Releases" else POSTS_PER_FEED

        for entry in reversed(feed.entries[:limit]):
            raw_id = entry.get("id") or entry.get("link") or ""
            raw_title = entry.get("title", "").strip()

            if any(k in source_name for k in ["Crunchyroll", "Ani-One", "Muse", "Alert"]):
                post_id = f"{raw_id}::{raw_title}"
            else:
                post_id = raw_id

            if not post_id or post_id in sent_posts:
                continue

            entry_dt = get_entry_datetime(entry)
            if entry_dt and entry_dt < CUTOFF_DATE:
                continue

            message, title, image_url, ok = build_message(source_name, entry, entry_dt)

            if not ok:
                print(f"Skipping untranslated post: {title[:40]}")
                continue

            if send_telegram_message(message, image_url):
                save_sent_post(post_id)
                sent_posts.add(post_id)
                new_posts_found += 1
                print(f"Posted: {title[:45]}")

    # 3. AniList Broadcast Schedule Backup
    anilist_releases = fetch_anilist_releases()
    for post_id, name, episode, air_ts, link, image_url in anilist_releases:
        if post_id in sent_posts:
            continue
        air_dt = datetime.fromtimestamp(air_ts, tz=timezone.utc)
        if air_dt < CUTOFF_DATE:
            continue

        published = format_to_ist(air_dt, {})
        msg = (
            "🚨 <b>#STREAMING_ALERT</b> 🚨\n\n"
            f"🎬 <b>Anime Name: {html.escape(name)}</b>\n"
            f"🔢 <b>Episode: Episode {episode}</b>\n"
            "🎙 <b>Audio Languages: Japanese</b>\n"
            "📝 <b>Subtitles: English</b>\n"
            f"📅 <b>Time: {html.escape(published)}</b>\n"
            f"🔗 <b>Platform: <a href=\"{html.escape(link, quote=True)}\">Crunchyroll</a></b>\n"
            f"{CHANNEL_FOOTER}"
        )
        if send_telegram_message(msg, image_url):
            save_sent_post(post_id)
            sent_posts.add(post_id)
            new_posts_found += 1
            print(f"AniList Alert: {name} - Ep {episode}")

    if new_posts_found == 0:
        print("No new updates found.")
    else:
        print(f"Total {new_posts_found} new posts sent.")


if __name__ == "__main__":
    main()
