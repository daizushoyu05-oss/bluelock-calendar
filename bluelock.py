import feedparser, re, hashlib, urllib.parse, json, os, sys, time
import requests
from datetime import date, timedelta

QUERIES = ["ブルーロック 発売", "ブルーロック 予約", "ブルーロック 開催",
           "ブルーロック 決定", "ブルーロック アニメ",
           "ブルーロック イベント", "ブルーロック コラボ"]

# 見出しにこの言葉があったらAIに渡さず除外（自由に追加OK）
EXCLUDE = ["舞台", "実写", "THE STAGE", "ミュージカル", "綱啓永", "高橋", "菊池"]

# 使うモデル名（上から順に試す）
MODELS = ["gemini-3.5-flash", "gemini-3.6-flash",
          "gemini-3.7-flash", "gemini-3.8-flash"]

# 予定名の末尾につける識別用の空白文字
MARK = "\u3164"

API_KEY = os.environ.get("GEMINI_API_KEY", "")
if not API_KEY:
    print("GEMINI_API_KEY が見つかりません")
    sys.exit(1)

PROMPT = """今日は__TODAY__です。以下は、アニメ「ブルーロック」に関するニュース記事の見出し一覧です。
各行は「番号|公開日|見出し」です。

見出しから、日付が書かれているグッズ・書籍・Blu-ray・イベント・コラボ・カフェ・くじなどの予定を抜き出し、JSONだけで返してください。

ルール:
- 舞台、実写、ドラマ、俳優の話題は除外
- アニメ本編の放送・配信、日付が書かれていない情報は除外
- 見出しに書かれていないことは推測しない
- 1つの記事から複数の予定を作ってよい（予約開始日と発売日が両方あるときなど）
- 同じ内容の重複は1つにまとめる
- 年が書かれていなければ公開日から推定する
- name: 短く。グッズ名・商品名・イベント名・店名だけ。「予約」「発売」は含めない
  例: まるほぺ / ウエハース / 単行本41巻 / アニメイトカフェ / カラオケBanBan
- kind: 予約開始なら"予約"、発売なら"発売"、イベント・カフェ・ポップアップ等なら"イベント"
- start: 開始日 YYYY-MM-DD、end: 終了日 YYYY-MM-DD（1日だけならnull）
- place: 場所（見出しに書かれている場合のみ、なければnull）
- note: 1行の概要。「12月下旬発売」などあいまいな情報もここに入れる（なければnull）
- article: 元になった記事の番号

返す形式:
{"events":[{"article":0,"name":"","kind":"","start":"","end":null,"place":null,"note":null}]}

見出し一覧:
__ARTICLES__
"""

today = date.today()
articles = {}

for q in QUERIES:
    url = ("https://news.google.com/rss/search?q="
           + urllib.parse.quote(q) + "&hl=ja&gl=JP&ceid=JP:ja")
    for e in feedparser.parse(url).entries:
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
        articles[e.link] = (title, pub)

items = list(articles.items())
print(len(items), "件の記事を見つけました")

# 記事が0件のときは、古いbluelock.icsを残すため、ここで止める
if not items:
    print("記事が取れなかったので、カレンダーは更新しません")
    sys.exit(1)


def ask(prompt):
    last = ""
    for model in MODELS:
        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               + model + ":generateContent")
        for attempt in range(2):
            try:
                r = requests.post(
                    url,
                    headers={"x-goog-api-key": API_KEY,
                             "Content-Type": "application/json"},
                    json={"contents": [{"parts": [{"text": prompt}]}],
                          "generationConfig": {
                              "temperature": 0,
                              "responseMimeType": "application/json"}},
                    timeout=120)
            except requests.RequestException as ex:
                last = model + ": " + str(ex)[:150]
                time.sleep(5)
                continue
            if r.status_code == 200:
                try:
                    parts = r.json()["candidates"][0]["content"]["parts"]
                    text = "".join(x.get("text", "") for x in parts).strip()
                    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
                    data = json.loads(text)
                    print("使用モデル:", model)
                    return data
                except Exception as ex:
                    last = model + ": 返答を読めませんでした " + str(ex)[:100]
                    break
            last = model + ": HTTP " + str(r.status_code) + " " + r.text[:200]
            if r.status_code in (429, 500, 503) and attempt == 0:
                time.sleep(20)
                continue
            break
    print("Gemini失敗:", last)
    return None


events = {}
failed = False

for i in range(0, len(items), 25):
    chunk = items[i:i + 25]
    listing = "\n".join(
        f"{n}|{pub}|{title}" for n, (link, (title, pub)) in enumerate(chunk))
    prompt = PROMPT.replace("__TODAY__", str(today)).replace("__ARTICLES__", listing)
    res = ask(prompt)
    if res is None:
        failed = True
        continue
    for ev in res.get("events", []):
        try:
            link, (title, pub) = chunk[int(ev["article"])]
            name = re.sub(r"(予約開始|予約|発売)$", "", str(ev["name"]).strip())
            kind = ev["kind"]
            d = date.fromisoformat(ev["start"])
            last = date.fromisoformat(ev["end"]) if ev.get("end") else d
        except Exception:
            continue
        if not name or kind not in ("予約", "発売", "イベント"):
            continue
        if last < d:
            last = d
        if last < today - timedelta(days=7):
            continue
        key = (name, kind, d)
        if key in events:
            continue
        summary = name + (kind if kind in ("予約", "発売") else "")
        desc = "\n".join(x for x in [ev.get("note"), "記事: " + title, link] if x)
        events[key] = dict(d=d, last=last, summary=summary,
                           place=ev.get("place"), desc=desc, link=link)

# 失敗したときは古いbluelock.icsを残すため、ここで止める
if failed:
    print("Geminiの処理に失敗したので、カレンダーは更新しません")
    sys.exit(1)


def esc(s):
    return (str(s).replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\n", "\\n"))


lines = ["BEGIN:VCALENDAR", "VERSION:2.0",
         "PRODID:-//bluelock-calendar//JP",
         "X-WR-CALNAME:ブルーロック情報"]
for key, v in events.items():
    uid = hashlib.md5("|".join(map(str, key)).encode()).hexdigest()
    end = v["last"] + timedelta(days=1)
    lines += ["BEGIN:VEVENT", f"UID:{uid}@bluelock",
              f"DTSTAMP:{today:%Y%m%d}T000000Z",
              f"DTSTART;VALUE=DATE:{v['d']:%Y%m%d}",
              f"DTEND;VALUE=DATE:{end:%Y%m%d}",
              "SUMMARY:" + esc(v["summary"]) + MARK]
    if v["place"]:
        lines.append("LOCATION:" + esc(v["place"]))
    lines += ["DESCRIPTION:" + esc(v["desc"]),
              "URL:" + v["link"], "END:VEVENT"]
lines.append("END:VCALENDAR")

with open("bluelock.ics", "w", encoding="utf-8", newline="") as f:
    f.write("\r\n".join(lines) + "\r\n")

print(len(events), "件のイベントを書き出しました")
