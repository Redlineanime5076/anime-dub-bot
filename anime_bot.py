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
MAX_AGE_HOURS = 48

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

JP_RE = re.compile(r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]")

LANGS = ["Hindi", "Tamil", "Telugu", "English", "Spanish", "Portuguese",
         "German", "French", "Italian", "Arabic", "Russian"]
_L = "|".join(LANGS)
AUDIO_RE = re.compile(
    rf"\b({_L})(?:\s*\([^)]*\))?\s+(?:Dub|Audio)\b|\(({_L})\)", re.IGNORECASE
)
TITLE_CLEAN_RE = re.compile(
    rf"\s*\((?:[^)]*\b(?:Dub|Audio)\b[^)]*|{_L})\)", re.IGNORECASE
)


# ---------- Helpers ----------
def detect_audios(text):
    """শুধু 'Hindi Dub' / 'Tamil Audio' / '(Telugu)' প্যাটার্ন থেকে ডাব ধরে।"""
    audios = []
    for m in AUDIO_RE.finditer(text or ""):
        lang = (m.group(1) or m.group(2)).title()
        label = f"{lang} Dub"
        if label not in audios:
            audios.append(label)
    return audios or ["Japanese"]


def split_title(title):
    clean = TITLE_CLEAN_RE.sub("", title).strip()
    if " - " in clean:
        parts = clean.split(" - ")
        return parts[0].strip(), " - ".join(parts[1:]).strip()
    m = re.split(r"\s+(Episode\s+\d+)", clean, flags=re.IGNORECASE)
    if len(m) > 1:
        return m[0].strip(), m[1].strip()
    return clean, "Episode Update"


def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def ep_key(name, episode):
    """Japanese/Sub রিলিজের ডুপ্লিকেট আটকানোর কী।"""
    num = re.search(r"(\d+)", str(episode))
    return f"ep::{norm(name)}::{num.group(1) if num else norm(episode)}"


def translate_if_japanese(text):
    if not text or not JP_RE.search(text):
        return text, True
    params = {"client": "gtx", "sl": "ja", "tl": "en", "dt": "t", "q": text}
    for attempt in range(3):
        try:
            res = requests.get(
                "https://translate.googleapis.com/translate_a/single",
                params=params, headers=HEADERS, timeout=12,
            )
            if res.status_code == 200:
                data = res.json()
                out = "".join(p[0] for p in data[0] if p[0])
                if out:
                    return out.strip(), True
        except Exception as e:
            print(f"Translation error (attempt {attempt + 1}): {e}")
        time.sleep(2)
    return text, False


def gnews(q, lang="en", country="US"):
    return (f"https://news.google.com/rss/search?q={quote(q)}"
            f"&hl={lang}-{country}&gl={country}&ceid={country}:{lang}")


def gnews_jp(q):
    return (f"https://news.google.com/rss/search?q={quote(q)}"
            f"&hl=ja&gl=JP&ceid=JP:ja")


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
    {"name": "JP Episode Preview", "url": gnews_jp("アニメ 第 先行カット OR あらすじ")},
    {"name": "JP Box Office Records", "url": gnews_jp("劇場アニメ 興行収入 突破")},
    {"name": "JP Ranking Record", "url": gnews_jp("アニメ ランキング 1位 獲得")},
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


# ---------- History ----------
def load_sent_posts():
    if not os.path.exists(HISTORY_FILE):
        return set()
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def save_sent_post(post_id):
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(f"{post_id}\n")


# ---------- Telegram ----------
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
        params={"chat_id": CHAT_ID, "user_id": bot_id}, timeout=15,
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
    for _ in range(3):
        try:
            data = requests.post(f"{API}/sendMessage", json=payload, timeout=15).json()
        except Exception as e:
            print(f"Network Error: {e}")
            time.sleep(3)
            continue
        if data.get("ok"):
            time.sleep(2.5)
            return True
        if data.get("error_code") == 429:
            time.sleep(data.get("parameters", {}).get("retry_after", 10) + 1)
            continue
        print(f"Telegram API Error: {data}")
        return False
    return False


def stream_alert(name, episode, audio, published, link):
    return (
        "🚨 <b>#STREAMING_ALERT</b> 🚨\n\n"
        f"🎬 <b>Anime Name:</b> {html.escape(name)}\n"
        f"🔢 <b>Episode:</b> {html.escape(str(episode))}\n"
        f"🎙 <b>Audio:</b> {html.escape(audio)}\n"
        f"📅 <b>Time:</b> <i>{html.escape(published)}</i>\n"
        f'🔗 <b>Platform:</b> <a href="{html.escape(link, quote=True)}">Crunchyroll</a>'
    )


# ---------- Sources ----------
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
            return parsedate_to_datetime(raw).astimezone(timezone.utc)
        except Exception:
            pass
    return None


def format_to_ist(dt, entry=None):
    if dt:
        ist = timezone(timedelta(hours=5, minutes=30))
        return dt.astimezone(ist).strftime("%d %b %Y, %I:%M %p IST")
    entry = entry or {}
    return (entry.get("published") or entry.get("pubDate") or "").strip()


def fetch_crunchyroll_calendar():
    results = []
    now = datetime.now(timezone.utc)
    for d in [now - timedelta(days=1), now]:
        url = f"https://www.crunchyroll.com/simulcastcalendar?date={d.strftime('%Y-%m-%d')}"
        h = dict(HEADERS)
        h["Referer"] = "https://www.crunchyroll.com/releasecalendar"
        try:
            res = requests.get(url, headers=h, timeout=15)
            if res.status_code != 200:
                print(f"Calendar blocked/failed: HTTP {res.status_code}")
                continue
            soup = BeautifulSoup(res.text, "html.parser")
            articles = soup.find_all("article", class_=re.compile(r"release"))
            print(f"Calendar {d.strftime('%Y-%m-%d')}: {len(articles)} releases found")

            for art in articles:
                t = art.find(class_=re.compile(r"season-name|series-title"))
                e = art.find(class_=re.compile(r"episode-name|episode-number"))
                a = art.find("a", href=True)
                if not t:
                    continue
                raw_title = t.get_text(strip=True)
                raw_ep = e.get_text(strip=True) if e else "Episode Update"
                link = a["href"] if a else "https://www.crunchyroll.com"
                if not link.startswith("http"):
                    link = f"https://www.crunchyroll.com{link}"

                audios = detect_audios(f"{raw_title} {raw_ep}")
                name = TITLE_CLEAN_RE.sub("", raw_title).strip()
                audio_txt = ", ".join(audios)
                post_id = f"cr-cal::{norm(name)}::{norm(raw_ep)}::{norm(audio_txt)}"
                results.append((post_id, name, raw_ep, audio_txt, link))
        except Exception as ex:
            print(f"Calendar Fetch Error: {ex}")
    return results


def fetch_anilist_releases(hours=ANILIST_HOURS):
    now = int(time.time())
    results = []
    for page in range(1, 4):
        try:
            res = requests.post(
                ANILIST_URL,
                json={"query": ANILIST_QUERY,
                      "variables": {"from": now - hours * 3600, "to": now, "page": page}},
                headers=HEADERS, timeout=15,
            )
            data = res.json().get("data", {}).get("Page", {})
        except Exception as e:
            print(f"AniList Error: {e}")
            break
        if not data or "airingSchedules" not in data:
            break
        for item in data["airingSchedules"]:
            media = item["media"]
            link = next((l["url"] for l in (media.get("externalLinks") or [])
                         if l.get("site") == "Crunchyroll"), None)
            if not link:
                continue
            title = media["title"].get("english") or media["title"].get("romaji") or "Unknown"
            results.append((f"anilist-{media['id']}-{item['episode']}",
                            title, item["episode"], item["airingAt"], link))
        if not data.get("pageInfo", {}).get("hasNextPage"):
            break
        time.sleep(1)
    return results


def build_news_message(source_name, entry, entry_dt):
    raw_title = entry.get("title", "Anime News Update").strip()
    link = entry.get("link", "").strip()
    desc = entry.get("description", "")
    published = format_to_ist(entry_dt, entry)

    if source_name == "Crunchyroll Latest Releases":
        audios = detect_audios(f"{raw_title} {desc}")
        name, episode = split_title(raw_title)
        msg = stream_alert(name, episode, ", ".join(audios), published, link)
        return msg, f"{name} - {episode}", True, (name, episode, audios)

    title, ok = translate_if_japanese(raw_title)
    msg = (
        f"🔥 <b>[{html.escape(source_name)}]</b>\n\n"
        f"📢 <b>{html.escape(title)}</b>\n\n"
    )
    if published:
        msg += f"📅 <i>{html.escape(published)}</i>\n"
    if link:
        msg += f'🔗 <a href="{html.escape(link, quote=True)}">Read Full Article</a>'
    return msg, title, ok, None


# ---------- Main ----------
def main():
    if not preflight_check():
        sys.exit(1)

    sent = load_sent_posts()
    new_count = 0
    min_dt = datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS)

    def mark(pid):
        save_sent_post(pid)
        sent.add(pid)

    # 1. Crunchyroll Calendar
    for post_id, name, episode, audio, link in fetch_crunchyroll_calendar():
        if post_id in sent:
            continue
        is_sub_only = audio == "Japanese"
        key = ep_key(name, episode)
        if is_sub_only and key in sent:
            mark(post_id)
            continue
        msg = stream_alert(name, episode, audio, format_to_ist(datetime.now(timezone.utc)), link)
        if send_telegram_message(msg):
            mark(post_id)
            if is_sub_only:
                mark(key)
            new_count += 1
            print(f"Calendar: {name} - {episode} ({audio})")

    # 2. RSS Feeds
    for feed_info in RSS_FEEDS:
        source = feed_info["name"]
        feed = fetch_feed(feed_info["url"])
        if not feed.entries:
            print(f"No entries: {source}")
            continue

        limit = POSTS_PER_CR if source == "Crunchyroll Latest Releases" else POSTS_PER_FEED
        for entry in reversed(feed.entries[:limit]):
            raw_id = entry.get("id") or entry.get("link") or ""
            raw_title = entry.get("title", "").strip()
            post_id = f"{raw_id}::{raw_title}" if source == "Crunchyroll Latest Releases" else raw_id
            if not post_id or post_id in sent:
                continue

            entry_dt = get_entry_datetime(entry)
            if entry_dt and entry_dt < min_dt:
                continue

            message, title, ok, cr = build_news_message(source, entry, entry_dt)
            if not ok:
                print(f"Skipping untranslated: {title[:40]}")
                continue

            key = None
            if cr and cr[2] == ["Japanese"]:
                key = ep_key(cr[0], cr[1])
                if key in sent:
                    mark(post_id)
                    continue

            if send_telegram_message(message):
                mark(post_id)
                if key:
                    mark(key)
                new_count += 1
                print(f"Posted: {title[:45]}")

    # 3. AniList Fallback (শুধু Japanese/Sub)
    for post_id, name, episode, air_ts, link in fetch_anilist_releases():
        if post_id in sent:
            continue
        air_dt = datetime.fromtimestamp(air_ts, tz=timezone.utc)
        if air_dt < min_dt:
            continue
        key = ep_key(name, episode)
        if key in sent:
            mark(post_id)
            continue
        msg = stream_alert(name, f"Episode {episode}", "Japanese", format_to_ist(air_dt), link)
        if send_telegram_message(msg):
            mark(post_id)
            mark(key)
            new_count += 1
            print(f"AniList: {name} - Ep {episode}")

    print("No new updates found." if new_count == 0 else f"Total {new_count} new posts sent.")


if __name__ == "__main__":
    main()
