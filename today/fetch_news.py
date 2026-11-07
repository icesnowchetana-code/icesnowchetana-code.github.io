"""抓各來源新聞，寫成 today/news.json。單一來源失敗不影響其他來源。"""
import html, json, re, sys, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
import xml.etree.ElementTree as ET

UA = "Mozilla/5.0 (compatible; ChetanaToday/1.0)"
OUT = Path(__file__).with_name("news.json")


def gn(query, days=2):
    q = urllib.parse.quote(query)
    return f"https://news.google.com/rss/search?q={q}+when:{days}d&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"


SECTIONS = [
    {"id": "design", "title": "設計與建築", "images": True, "feeds": [
        "https://www.dezeen.com/feed/",
        "https://www.designboom.com/feed/",
        "https://feeds.feedburner.com/Archdaily",
        "https://www.yankodesign.com/feed/",
    ]},
    {"id": "ai", "title": "AI 與科技", "images": True, "feeds": [
        "https://technews.tw/feed/",
        "https://www.ithome.com.tw/rss",
        "https://www.inside.com.tw/feed/rss",
        "https://www.bnext.com.tw/rss",
    ]},
    {"id": "interior", "title": "室內設計話題", "images": False, "feeds": [gn("室內設計"), gn("裝潢 住宅")]},
    {"id": "taiwan", "title": "台灣焦點", "images": False, "feeds": ["https://news.google.com/rss?hl=zh-TW&gl=TW&ceid=TW:zh-Hant"]},
    {"id": "mingli", "title": "紫微・命理・星座", "images": True, "per_feed": 5,
     "exclude": "選|市長|縣長|立委|當選|藍白|股災|台股|政",
     "match": "星座|運勢|紫微|命理|八字|易經|塔羅|生肖|風水|占卜|水逆|上升|月亮|命盤|流年|開運|太陽", "feeds": [
        "https://www.elle.com/tw/rss/all.xml/",
        "https://www.cosmopolitan.com/tw/rss/all.xml/",
        "https://www.harpersbazaar.com/tw/rss/all.xml/",
        "https://www.womenshealthmag.com/tw/rss/all.xml/",
        "https://www.marieclaire.com.tw/rss.xml",
        "https://www.vogue.com.tw/feed/rss",
        "https://www.bella.tw/rss",
        "https://www.wowlavie.com/rss.xml",
        gn("紫微斗數", 14), gn("星座 運勢", 3), gn("八字 命理", 14), gn("易經 占卜", 14),
    ]},
    {"id": "money", "title": "財經", "images": False, "feeds": [gn("台股"), gn("房市")]},
    {"id": "kaohsiung", "title": "高雄", "images": False, "feeds": [gn("高雄")]},
    {"id": "japan", "title": "日本與旅行", "images": True, "per_feed": 4, "feeds": [
        "https://livejapan.com/zh-tw/rss/",
        "https://matcha-jp.com/tw/feed",
        "https://tw.fun-japan.jp/feed",
        "https://tsunagujapan.com/zh-hant/feed/",
        "https://www.gltjp.com/zh-hant/rss/",
        "https://www.tokyoweekender.com/feed/",
        "https://soranews24.com/feed/",
        "https://www.japan-guide.com/news/rss.xml",
    ]},
    {"id": "life", "title": "生活與健康", "images": False, "feeds": [gn("健康 飲食"), gn("女性 創業")]},
]
MARKETS = [("^TWII", "台股加權"), ("^DJI", "道瓊"), ("^IXIC", "那斯達克"), ("2330.TW", "台積電")]


def get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def local(tag):
    return tag.rsplit("}", 1)[-1].lower()


def strip(text):
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text or "", flags=re.S | re.I)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    return re.sub(r"\s+", " ", text).strip()


def https(url):
    url = html.unescape((url or "").strip())
    if url.startswith("//"):
        url = "https:" + url
    return url if url.startswith("https://") else ""


def image_of(node, body):
    for child in node.iter():
        tag = local(child.tag)
        if tag in ("thumbnail", "content", "enclosure"):
            url = https(child.get("url"))
            kind = child.get("type") or child.get("medium") or ""
            if url and (tag == "thumbnail" or "image" in kind or re.search(r"\.(jpe?g|png|webp)", url, re.I)):
                return url
    m = re.search(r"<img[^>]+src=[\"']([^\"']+)", body or "", re.I)
    return https(m.group(1)) if m else ""


def parse_date(text):
    if not text:
        return 0
    try:
        return int(parsedate_to_datetime(text).timestamp())
    except Exception:
        pass
    try:
        return int(datetime.fromisoformat(text.strip().replace("Z", "+00:00")).timestamp())
    except Exception:
        return 0


def parse(url):
    root = ET.fromstring(get(url))
    feed_title = ""
    for child in root.iter():
        if local(child.tag) == "title":
            feed_title = strip(child.text)
            break
    out = []
    for node in root.iter():
        if local(node.tag) not in ("item", "entry"):
            continue
        data = {}
        for child in node:
            tag = local(child.tag)
            if tag == "link":
                data["link"] = child.get("href") or child.text or ""
            elif tag not in data or tag == "encoded":
                data[tag] = "".join(child.itertext())
        body = data.get("encoded") or data.get("content") or data.get("description") or data.get("summary") or ""
        link = https(data.get("link"))
        title = strip(data.get("title"))
        if not link or not title:
            continue
        source = strip(data.get("source")) or feed_title
        if " - " in title and "news.google.com" in url:
            title = title.rsplit(" - ", 1)[0]
        out.append({
            "title": title[:120],
            "url": link,
            "source": source[:30],
            "summary": "" if "news.google.com" in url else strip(body)[:110],
            "image": image_of(node, body),
            "time": parse_date(data.get("pubdate") or data.get("published") or data.get("updated") or data.get("date")),
        })
    return out


def og_image(item):
    if item["image"] or "news.google.com" in item["url"]:
        return item
    try:
        page = get(item["url"], 8)[:300000].decode("utf-8", "ignore")
        m = re.search(r"<meta[^>]+(?:property|name)=[\"']og:image[\"'][^>]+content=[\"']([^\"']+)", page, re.I) \
            or re.search(r"<meta[^>]+content=[\"']([^\"']+)[\"'][^>]+(?:property|name)=[\"']og:image", page, re.I)
        if m:
            item["image"] = https(m.group(1))
    except Exception:
        pass
    return item


def section(sec):
    items, seen, report = [], set(), []
    for url in sec["feeds"]:
        try:
            got = parse(url)
            report.append(f"{sec['id']} ok {len(got)} {url[:60]}")
            if sec.get("exclude"):
                got = [i for i in got if not re.search(sec["exclude"], i["title"])]
            if sec.get("match"):
                got = [i for i in got if re.search(sec["match"], i["title"])]
            if sec.get("per_feed"):
                got = sorted(got, key=lambda i: i["time"], reverse=True)[:sec["per_feed"]]
            items += got
        except Exception as e:
            report.append(f"{sec['id']} FAIL {type(e).__name__} {url[:60]}")
    items.sort(key=lambda i: i["time"], reverse=True)
    unique = []
    for it in items:
        key = re.sub(r"\W", "", it["title"])[:24]
        if key not in seen:
            seen.add(key)
            unique.append(it)
    # 每個來源最多 6 則，避免一家佔滿
    count, mixed = {}, []
    for it in unique:
        count[it["source"]] = count.get(it["source"], 0) + 1
        if count[it["source"]] <= 6:
            mixed.append(it)
    unique = mixed[:30] if sec["images"] else mixed[:18]
    if sec["images"]:
        with ThreadPoolExecutor(6) as ex:
            unique = list(ex.map(og_image, unique))
        pictured = [i for i in unique if i["image"]]
        if len(pictured) >= 6:
            unique = pictured
        unique = unique[:18]
    else:
        for it in unique:
            it["image"] = ""
    print("\n".join(report), flush=True)
    return {"id": sec["id"], "title": sec["title"], "images": sec["images"], "items": unique}


def market(sym, name):
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/" + urllib.parse.quote(sym) + "?interval=1d&range=1d"
        meta = json.loads(get(url))["chart"]["result"][0]["meta"]
        price, prev = meta["regularMarketPrice"], meta.get("chartPreviousClose") or meta.get("previousClose")
        return {"name": name, "price": price, "change": round((price / prev - 1) * 100, 2) if prev else None}
    except Exception as e:
        print("market FAIL", sym, type(e).__name__, flush=True)
        return None


def main():
    old = json.loads(OUT.read_text("utf-8")) if OUT.exists() else {}
    prev = {s["id"]: s for s in old.get("sections", [])}
    sections = []
    for sec in SECTIONS:
        new = section(sec)
        # 這次全部抓不到就保留上一次的內容
        sections.append(new if new["items"] or sec["id"] not in prev else prev[sec["id"]])
    markets = [m for m in (market(s, n) for s, n in MARKETS) if m] or old.get("markets", [])
    total = sum(len(s["items"]) for s in sections)
    if total == 0:
        sys.exit("no items from any feed")
    OUT.write_text(json.dumps({
        "updated": int(datetime.now(timezone.utc).timestamp()),
        "markets": markets,
        "sections": sections,
    }, ensure_ascii=False, indent=0), "utf-8")
    print("wrote", total, "items")


if __name__ == "__main__":
    main()
