import feedparser, re, hashlib, urllib.parse
from datetime import date, timedelta

QUERIES = ["ブルーロック グッズ 発売", "ブルーロック 予約", "ブルーロック イベント 開催"]
today = date.today()
events = {}

for q in QUERIES:
    url = ("https://news.google.com/rss/search?q="
           + urllib.parse.quote(q) + "&hl=ja&gl=JP&ceid=JP:ja")
    for e in feedparser.parse(url).entries:
        title = e.title
        if "ブルーロック" not in title:
            continue
        m = re.search(r"(\d{1,2})月(\d{1,2})日", title)
        if not m:
            continue
        try:
            d = date(today.year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            continue
                if d < today - timedelta(days=30):
            if d.month <= 2 and today.month >= 11:
                d = d.replace(year=today.year + 1)
            else:
                continue

        events[e.link] = (d, title)

lines = ["BEGIN:VCALENDAR", "VERSION:2.0",
         "PRODID:-//bluelock-calendar//JP",
         "X-WR-CALNAME:ブルーロック情報"]
for link, (d, title) in events.items():
    uid = hashlib.md5(link.encode()).hexdigest()
    end = d + timedelta(days=1)
    lines += ["BEGIN:VEVENT", f"UID:{uid}@bluelock",
              f"DTSTAMP:{today:%Y%m%d}T000000Z",
              f"DTSTART;VALUE=DATE:{d:%Y%m%d}",
              f"DTEND;VALUE=DATE:{end:%Y%m%d}",
              "SUMMARY:" + title.replace(",", "，"),
              "URL:" + link, "END:VEVENT"]
lines.append("END:VCALENDAR")

with open("bluelock.ics", "w", encoding="utf-8", newline="") as f:
    f.write("\r\n".join(lines) + "\r\n")

print(len(events), "件のイベントを書き出しました")
