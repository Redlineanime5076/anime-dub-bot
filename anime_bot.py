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
from bs4 import BeautifulSoup

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = "@databaceforredlineanime"

if not BOT_TOKEN:
    print("Error: BOT_TOKEN not found in GitHub Secrets.")
    sys.exit(1)

POSTS_PER_FEED = 3
POSTS_PER_CR = 25
HISTORY_FILE = "sent_posts.txt"
SHOW_LINK_PREVIEW = True
ANILIST_HOURS = 8

# Global headers for all standard RSS feeds
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5"
}

CUTOFF_DATE = datetime(2026, 10, 29, 0, 0, 0, tzinfo=timezone.utc)
JP_RE = re.compile(r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]")


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


def gnews(q, lang="en", country="US"):
    return f"https://news.google.com/rss/search?q={quote(q)}&hl={lang}-{country}&gl={country}&ceid={country}:{lang}"


def gnews_jp(q):
    return f"https://news.google.com/rss/search?q={quote(q)}&hl=ja&gl=JP&ceid=JP:ja"


RSS_FEEDS = [
    {"name": "Crunchyroll Latest Releases", "url": "https://www.crunchyroll.com/rss/anime"},
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
    {"name": "Comic Natalie (JP)", "url": "https://natalie.mu/comic/feed/news"},
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
        externalLinks { site url }
      }
    }
  }
}
"""


def fetch_crunchyroll_calendar():
    """Fetches the Crunchyroll release calendar with Indian locale headers and cookies."""
    results = []
    now = datetime.now(timezone.utc)
    date_strs = [(now - timedelta(days=1)).strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d")]

    india_headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
        "Accept-Language": "en-IN,en;q=0.9,hi-IN;q=0.8,hi;q=0.7",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://www.crunchyroll.com/releasecalendar",
        "Cookie": "locale=en-IN; c_locale=en-IN;"
    }

    for d_str in date_strs:
        url = f"https://www.crunchyroll.com/simulcastcalendar?date={d_str}"

        try:
            res = requests.get(url, headers=india_headers, timeout=20)
            if res.status_code != 200:
                continue

            soup = BeautifulSoup(res.text, "html.parser")
            articles = soup.find_all("article", class_=re.compile(r"release"))

            for art in articles:
                title_elem = art.find(class_=re.compile(r"season-name|series-title"))
                ep_elem = art.find(class_=re.compile(r"episode-name|episode-number"))
                link_elem = art.find("a", href=True)

                if not title_elem:
                    continue

                raw_title = title_elem.get_text(strip=True)
                raw_ep = ep_elem.get_text(strip=True) if ep_elem else "Episode Update"
                link = link_elem["href"] if link_elem else "https://www.crunchyroll.com"
                if not link.startswith("http"):
                    link = f"https://www.crunchyroll.com{link}"

                full_text = f"{raw_title} {raw_ep} {art.get_text()}"
                audios = []

                target_langs = ["Hindi", "Tamil", "Telugu", "English", "Japanese", "Spanish", "Portuguese", "German", "French", "Italian"]
                for lang in target_langs:
                    if re.search(rf'\b{lang}\b', full_text, re.IGNORECASE):
                        label = f"{lang.title()} Dub" if lang.lower() != "japanese" else "Japanese"
                        if label not in audios:
                            audios.append(label)

                if not audios:
                    audios.append("Japanese")

                post_id = f"cr-cal-{raw_title}-{raw_ep}-{'-'.join(audios)}"
                results.append((post_id, raw_title, raw_ep, ", ".join(audios), link))

        except Exception as e:
            print(f"Calendar Fetch Error: {e}")

    return results


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
            post_id = f"anilist-{media['id']}-{item['episode']}"
            results.append((post_id, title, item["episode"], item["airingAt"], link))

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
            print(f"Network Error: {e}")
            time.sleep(3)
            continue

        if data.get("ok"):
            time.sleep(2.5)
            return True

        if data.get("error_code") == 429:
            wait = data.get("parameters", {}).get("retry_after", 10)
            print(f"Rate limit, waiting {wait} seconds...")
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


def parse_crunchyroll_details(title, desc=""):
    anime_name = title
    episode = "Episode Update"
    audios = []
    subtitles = ["English"]

    full_text = f"{title} {desc}"

    target_langs = ["Hindi", "Tamil", "Telugu", "English", "Japanese", "Spanish", "Portuguese", "German", "French", "Italian"]
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

    clean_title = re.sub(r'\(([^)]+Dub|[^)]+Audio|Hindi|Tamil|Telugu|English)\)', '', title, flags=re.IGNORECASE).strip()

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

    if source_name == "Crunchyroll Latest Releases":
        anime_name, episode, audio, subs = parse_crunchyroll_details(raw_title, desc)
        msg = (
            "🚨 <b>#STREAMING_ALERT</b> 🚨\n\n"
            f"🎬 <b>Anime Name:</b> {html.escape(anime_name)}\n"
            f"🔢 <b>Episode:</b> {html.escape(episode)}\n"
            f"🎙 <b>Audio Languages:</b> {html.escape(audio)}\n"
            f"📝 <b>Subtitles:</b> {html.escape(subs)}\n"
            f"📅 <b>Time:</b> <i>{html.escape(published)}</i>\n"
            f"🔗 <b>Platform:</b> <a href=\"{html.escape(link, quote=True)}\">Crunchyroll</a>"
        )
        return msg, f"{anime_name} - {episode}", True

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

    # 1. Crunchyroll Indian Release Calendar Scraping
    cal_releases = fetch_crunchyroll_calendar()
    for post_id, name, episode, audio, link in cal_releases:
        if post_id in sent_posts:
            continue

        now_dt = datetime.now(timezone.utc)
        published = format_to_ist(now_dt, {})
        msg = (
            "🚨 <b>#STREAMING_ALERT</b> 🚨\n\n"
            f"🎬 <b>Anime Name:</b> {html.escape(name)}\n"
            f"🔢 <b>Episode:</b> {html.escape(episode)}\n"
            f"🎙 <b>Audio Languages:</b> {html.escape(audio)}\n"
            "📝 <b>Subtitles:</b> English\n"
            f"📅 <b>Time:</b> <i>{html.escape(published)}</i>\n"
            f"🔗 <b>Platform:</b> <a href=\"{html.escape(link, quote=True)}\">Crunchyroll</a>"
        )
        if send_telegram_message(msg):
            save_sent_post(post_id)
            sent_posts.add(post_id)
            new_posts_found += 1
            print(f"Posted Calendar Release: {name} - {episode} ({audio})")

    # 2. Standard Global RSS Feeds
    for feed_info in RSS_FEEDS:
        source_name = feed_info["name"]
        feed = fetch_feed(feed_info["url"])
        if not feed.entries:
            continue

        limit = POSTS_PER_CR if source_name == "Crunchyroll Latest Releases" else POSTS_PER_FEED

        for entry in reversed(feed.entries[:limit]):
            raw_id = entry.get("id") or entry.get("link") or ""
            raw_title = entry.get("title", "").strip()

            if source_name == "Crunchyroll Latest Releases":
                post_id = f"{raw_id}::{raw_title}"
            else:
                post_id = raw_id

            if not post_id or post_id in sent_posts:
                continue

            entry_dt = get_entry_datetime(entry)
            if entry_dt and entry_dt < CUTOFF_DATE:
                continue

            message, title, ok = build_message(source_name, entry, entry_dt)

            if not ok:
                print(f"Skipping untranslated post: {title[:40]}")
                continue

            if send_telegram_message(message):
                save_sent_post(post_id)
                sent_posts.add(post_id)
                new_posts_found += 1
                print(f"Posted: {title[:45]}")

    # 3. AniList Schedule Backup
    anilist_releases = fetch_anilist_releases()
    for post_id, name, episode, air_ts, link in anilist_releases:
        if post_id in sent_posts:
            continue
        air_dt = datetime.fromtimestamp(air_ts, tz=timezone.utc)
        if air_dt < CUTOFF_DATE:
            continue

        published = format_to_ist(air_dt, {})
        msg = (
            "🚨 <b>#STREAMING_ALERT</b> 🚨\n\n"
            f"🎬 <b>Anime Name:</b> {html.escape(name)}\n"
            f"🔢 <b>Episode:</b> Episode {episode}\n"
            "🎙 <b>Audio Languages:</b> Japanese\n"
            "📝 <b>Subtitles:</b> English\n"
            f"📅 <b>Time:</b> <i>{html.escape(published)}</i>\n"
            f"🔗 <b>Platform:</b> <a href=\"{html.escape(link, quote=True)}\">Crunchyroll</a>"
        )
        if send_telegram_message(msg):
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
