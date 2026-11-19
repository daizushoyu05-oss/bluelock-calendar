import feedparser, re, hashlib, urllib.parse
from datetime import date, timedelta

QUERIES = ["ブルーロック 発売", "ブルーロック 予約", "ブルーロック 開催", "ブルーロック 決定"]

# タイトルにこの言葉が入っていたら除外（自由に追加OK）
EXCLUDE = ["舞台", "実写", "THE STAGE", "ミュージカル","綱","高橋","菊池"]

# 予定名を短くする言葉（自由に追加OK）
SHORT = ["アニメイトカフェ", "コラボカフェ", "ローソン", "ポップアップ",
         "一番くじ", "ガチャ", "フェア", "カフェ",
         "コミックス", "単行本", "Blu-ray", "DVD","グッズ"]

today = date.today()
events = {}
seen = set()

for q in QUERIES:
    url = ("https://news.google.com/rss/search?q="
           + urllib.parse.quote(q) + "&hl=ja&gl=JP&ceid=JP:ja")
    for e in feedparser.parse(url).entries:
        # 末尾の「 - サイト名」を削る
        title = re.sub(r"\s[-－–—]\s[^-－–—]*$", "", e.title)
        if "ブルーロック" not in title:
            continue
        if any(w in title for w in EXCLUDE):
            continue
        p = e.get("published_parsed")
        if not p:
            continue
        pub = date(p[0], p[1], p[2])
        if pub < today - timedelta(days=60):
            continue

        # 期間（12月1日〜25日 など）を先に探す
        r = re.search(
            r"(\d{1,2})月(\d{1,2})日\s*[〜～~\-–]\s*(?:(\d{1,2})月)?(\d{1,2})日?",
            title)
        if r:
            sm, sd = int(r.group(1)), int(r.group(2))
            em = int(r.group(3)) if r.group(3) else sm
            ed = int(r.group(4))
        else:
            m = re.search(r"(\d{1,2})月(\d{1,2})日", title)
            if not m:
                continue
            sm, sd = int(m.group(1)), int(m.group(2))
            em, ed = sm, sd

        y = re.search(r"(20\d{2})年", title)
        year = int(y.group(1)) if y else pub.year
        try:
            d = date(year, sm, sd)
            if not y and d < pub - timedelta(days=30):
                year += 1
                d = date(year, sm, sd)
            last = date(year, em, ed)
            if last < d:
                last = date(year + 1, em, ed)
        except ValueError:
            continue
        if last < today - timedelta(days=7):
            continue

        # 予定名を作る
        if "予約" in title:
            tag = "予約"
        elif "発売" in title:
            tag = "発売"
        else:
            tag = "開催"
        name = next((w for w in SHORT if w in title), None)
        summary = f"【{tag}】ブルーロック {name}" if name else f"【{tag}】{title}"

        if (d, summary) in seen:
            continue
        seen.add((d, summary))
        events[e.link] = (d, last, summary)

lines = ["BEGIN:VCALENDAR", "VERSION:2.0",
         "PRODID:-//bluelock-calendar//JP",
         "X-WR-CALNAME:ブルーロック情報"]
for link, (d, last, summary) in events.items():
    uid = hashlib.md5(link.encode()).hexdigest()
    end = last + timedelta(days=1)
    lines += ["BEGIN:VEVENT", f"UID:{uid}@bluelock",
              f"DTSTAMP:{today:%Y%m%d}T000000Z",
              f"DTSTART;VALUE=DATE:{d:%Y%m%d}",
              f"DTEND;VALUE=DATE:{end:%Y%m%d}",
              "SUMMARY:" + summary.replace(",", "，"),
              "URL:" + link, "END:VEVENT"]
lines.append("END:VCALENDAR")

with open("bluelock.ics", "w", encoding="utf-8", newline="") as f:
    f.write("\r\n".join(lines) + "\r\n")

print(len(events), "件のイベントを書き出しました")
