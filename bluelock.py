import feedparser, re, hashlib, urllib.parse, json, os, sys, time
import requests
from datetime import date, timedelta

QUERIES = ["ブルーロック 発売", "ブルーロック 予約", "ブルーロック 開催",
           "ブルーロック 決定", "ブルーロック アニメ",
           "ブルーロック イベント", "ブルーロック コラボ",
           "ブルーロック 新グッズ", "ブルーロック 受注",
           "ブルーロック 販売", "ブルーロック ポップアップ"]

# 見出しにこの言葉があったらAIに渡さず除外（自由に追加OK）
EXCLUDE = ["舞台", "実写", "THE STAGE", "ミュージカル", "綱啓永", "高橋", "菊池"]

# 使うモデル名（上から順に試す）
MODELS = ["gemini-3.8-flash", "gemini-3.7-flash",
          "gemini-3.6-flash", "gemini-3.5-flash"]

# 2段目の検索テーマ（自由に追加OK。増やすと検索回数も増えます）
THEMES = [
    "単行本・Blu-ray・DVD・CD・ゲームなど、書籍や映像・音楽の発売",
    "コラボカフェ・ポップアップストア・展示・コラボキャンペーンなど、店舗や企業とのイベント",
    "新しいグッズの予約・受注・通販（食品・食玩・雑貨・くじなど、どこの店・企業でも）",
    "AGFなど毎年開かれるイベントへの出展と、イベント後の事後通販",
]

# 予定名の末尾につける識別用の空白文字
MARK = "\u3164"

API_KEY = os.environ.get("GEMINI_API_KEY", "")
if not API_KEY:
    print("GEMINI_API_KEY が見つかりません")
    sys.exit(1)

FORMAT = """返す形式（JSONだけを返す）:
{"events":[{"article":0,"name":"","kind":"","start":"","end":null,"place":null,"note":null,"source":null}]}

各項目:
- name: 短く。グッズ名・商品名・イベント名・店名だけ。「予約」「発売」は含めない
  例: まるほぺ / ウエハース / 単行本41巻 / アニメイトカフェ / カラオケBanBan
- kind: 予約開始・受注開始なら"予約"、発売・販売開始なら"発売"、イベント・カフェ・ポップアップ・展示等なら"イベント"
- start: 開始日 YYYY-MM-DD（日付が確定していないものは予定に含めない）
- end: 終了日 YYYY-MM-DD（1日だけ、または不明ならnull）
- place: 場所（分かる場合のみ、なければnull）
- note: 1〜2行の概要。内容・価格・特典・「12月下旬発売」などあいまいな情報もここに入れる（なければnull）
- article: 元になった記事の番号（検索の場合は0）
- source: 情報源のURL（分かる場合のみ、なければnull）
"""

PROMPT_A = """今日は__TODAY__です。以下は、アニメ「ブルーロック」に関するニュース記事の見出し一覧です。
各行は「番号|公開日|見出し」です。

見出しから、日付が書かれているグッズ・書籍・Blu-ray・イベント・コラボ・カフェ・くじなどの予定を抜き出してください。

ルール:
- 舞台、実写、ドラマ、俳優の話題は除外
- アニメ本編の放送・配信は除外
- 見出しに書かれていないことは推測しない
- 1つの記事から複数の予定を作ってよい（予約開始日と発売日が両方あるときなど）
- 年が書かれていなければ公開日から推定する

""" + FORMAT + """
見出し一覧:
__ARTICLES__
"""

PROMPT_B = """今日は__TODAY__です。Google検索を使って、アニメ「ブルーロック」の、今日以降に始まる、または現在開催・販売中の「__THEME__」を調べてください。

ルール:
- 公式サイト、公式アカウント、ショップの商品ページ、信頼できるニュースの情報だけを使う
- 舞台、実写、ドラマ、俳優の話題は除外
- 分からないことは推測せず、null にする。日付が確定していないものは予定に含めない
- 別の作品の情報を混ぜない
- 最大15件まで

""" + FORMAT

today = date.today()
articles = {}
UA = "Mozilla/5.0 (compatible; bluelock-calendar)"

for q in QUERIES:
    url = ("https://news.google.com/rss/search?q="
           + urllib.parse.quote(q) + "&hl=ja&gl=JP&ceid=JP:ja")
    feed = feedparser.parse(url, agent=UA)
    print("検索:", q, "| 状態:", getattr(feed, "status", "なし"),
          "| 取得:", len(feed.entries), "件")
    for e in feed.entries:
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

# 記事が0件のときは、古いbluelock.icsを残すためここで止める
if not items:
    print("記事が取れなかったので、カレンダーは更新しません")
    sys.exit(1)


def ask(prompt, search=False):
    last = ""
    for model in MODELS:
        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               + model + ":generateContent")
        body = {"contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0}}
        if search:
            body["tools"] = [{"google_search": {}}]
        else:
            body["generationConfig"]["responseMimeType"] = "application/json"
        for attempt in range(2):
            try:
                r = requests.post(
                    url,
                    headers={"x-goog-api-key": API_KEY,
                             "Content-Type": "application/json"},
                    json=body, timeout=180)
            except requests.RequestException as ex:
                last = model + ": " + str(ex)[:150]
                print("  失敗:", last)
                time.sleep(5)
                continue
            if r.status_code == 200:
                try:
                    parts = r.json()["candidates"][0]["content"]["parts"]
                    text = "".join(x.get("text", "") for x in parts)
                    a, b = text.find("{"), text.rfind("}")
                    data = json.loads(text[a:b + 1])
                    print("使用モデル:", model, "(検索あり)" if search else "")
                    return data
                except Exception as ex:
                    last = model + ": 返答を読めませんでした " + str(ex)[:100]
                    print("  失敗:", last)
                    break
            last = (model + ": HTTP " + str(r.status_code) + " "
                    + r.text.replace("\n", " ")[:200])
            print("  失敗:", last)
            if r.status_code in (429, 500, 503) and attempt == 0:
                time.sleep(20)
                continue
            break
    print("Gemini失敗: 全部のモデルで失敗しました")
    return None


events = {}


def add(ev, link, title, from_search):
    try:
        name = re.sub(r"(予約開始|予約|発売)$", "", str(ev["name"]).strip())
        kind = ev["kind"]
        d = date.fromisoformat(ev["start"])
        last = date.fromisoformat(ev["end"]) if ev.get("end") else d
    except Exception:
        return False
    if not name or kind not in ("予約", "発売", "イベント"):
        return False
    if last < d:
        last = d
    if last < today - timedelta(days=7):
        return False
    for (n2, k2, d2) in events:
        if k2 == kind and (name in n2 or n2 in name) and abs((d - d2).days) <= 7:
            return False
    summary = name + (kind if kind in ("予約", "発売") else "")
    src = ev.get("source") or ""
    if from_search:
        link = src if src.startswith("http") else ""
        parts = ["【検索で補完・要確認】", ev.get("note"),
                 ("情報源: " + link) if link else None]
    else:
        parts = [ev.get("note"), "記事: " + title, link]
    events[(name, kind, d)] = dict(
        d=d, last=last, summary=summary, place=ev.get("place"),
        desc="\n".join(x for x in parts if x), link=link)
    return True


# ---- 1段目：ニュースの見出し ----
failed = False
for i in range(0, len(items), 25):
    chunk = items[i:i + 25]
    listing = "\n".join(
        f"{n}|{pub}|{title}" for n, (link, (title, pub)) in enumerate(chunk))
    res = ask(PROMPT_A.replace("__TODAY__", str(today))
              .replace("__ARTICLES__", listing))
    if res is None:
        failed = True
        continue
    for ev in res.get("events", []):
        try:
            link, (title, pub) = chunk[int(ev["article"])]
        except Exception:
            continue
        add(ev, link, title, False)
    time.sleep(3)

# 失敗したときは古いbluelock.icsを残すため、ここで止める
if failed:
    print("1段目のGeminiの処理に失敗したので、カレンダーは更新しません")
    sys.exit(1)

n1 = len(events)
print("1段目（見出し）:", n1, "件")

# ---- 2段目：Google検索で補完（失敗しても止めない） ----
for theme in THEMES:
    res = ask(PROMPT_B.replace("__TODAY__", str(today))
              .replace("__THEME__", theme), search=True)
    if res is None:
        print("検索に失敗したテーマ:", theme[:20])
        continue
    for ev in res.get("events", []):
        add(ev, "", "", True)
    time.sleep(3)

print("2段目（検索）で追加:", len(events) - n1, "件")

# 予定が0件のときも、古いbluelock.icsを残す
if not events:
    print("予定が0件だったので、カレンダーは更新しません")
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
    lines.append("DESCRIPTION:" + esc(v["desc"]))
    if v["link"]:
        lines.append("URL:" + v["link"])
    lines.append("END:VEVENT")
lines.append("END:VCALENDAR")

with open("bluelock.ics", "w", encoding="utf-8", newline="") as f:
    f.write("\r\n".join(lines) + "\r\n")

print(len(events), "件のイベントを書き出しました")
