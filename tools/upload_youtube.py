#!/usr/bin/env python3
"""
upload_youtube.py — Upload narrated shorts to YouTube via Data API v3.

Usage:
  python tools/upload_youtube.py --auth          # First time: OAuth browser login
  python tools/upload_youtube.py --upload-all    # Upload all 5 episodes
  python tools/upload_youtube.py --upload 1      # Upload episode 1 only
  python tools/upload_youtube.py --list          # Show queued episodes with status

OAuth token is saved to tools/youtube_token.json (gitignored).
Credentials: tools/client_secret.json
Episodes: narrated-shorts/posledniy-vulkan-shorts/scripts.json
Videos:   narrated-shorts/posledniy-vulkan-shorts/output/
"""
import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERIES = "posledniy-vulkan-shorts"
SERIES_DIR = os.path.join(ROOT, "narrated-shorts", SERIES)
SCRIPTS = os.path.join(SERIES_DIR, "scripts.json")
OUTPUT_DIR = os.path.join(SERIES_DIR, "output")
CLIENT_SECRET = os.path.join(ROOT, "tools", "client_secret.json")
TOKEN_FILE = os.path.join(ROOT, "tools", "youtube_token.json")

SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube"]

# Google Drive file IDs in order received from user
DRIVE_FILE_IDS = [
    "105fSw49J5sK6-nytXtQHfMv3NPXpnO3P",  # ep 1
    "1AWwFU6mId6Y_8DHqWLPKjfIndCdXaiin",  # ep 2
    "1DlIuDsCVoTBY1Pz7Y3KXIMzJ7uzn7NKH",  # ep 3
    "1k4ANMlUh9621nFrFP24RUnctaJpYzr1i",  # ep 4
    "1kY4U0Zs5eouRAUNjOQbJyUAtwSQqriud",  # ep 5
]

TITLES = [
    "Он дошёл последним. И его никто не остановил",
    "Его клиенты возвращались всегда. Благодаря одной цифре",
    "Его трижды просили развернуться. Трижды он не послушал",
    "Сдаться в начале ничего не стоит. Сдаться у цели — стоит всё",
    "Одно число стоило две жизни. Рассветом оно ничего не значило",
    "Ему платили за то, чтобы говорить это вслух. Его не послушали",
    "На другой стороне горы стоял его двойник. Только без клиента",
    "Он спас троих, пойдя обратно в бурю. Обратно он не вернулся",
]

DESCRIPTIONS = [
    "10 мая 1996 года последним на вершину Эвереста поднялся почтальон из городка под Сиэтлом. "
    "Ему было 46 лет, звали его Дуглас Хансен. Годом раньше он уже стоял здесь — и тогда повернул вниз. "
    "Весь следующий год он копил, записывался и шёл снова.\n\n"
    "На вершину он вышел около пяти вечера. Кислород кончился почти сразу. Тела его не нашли.\n\n"
    "Но странно здесь не то, что он дошёл. Странно, что его никто не развернул.\n\n"
    "#Эверест #1996 #ДугласХансен #История #Горы #RobHall #Himalayas #MountEverest #Shorts",

    "Роб Холл водил людей на восьмитысячники и славился одним: клиенты у него возвращались. "
    "Не выносливостью, не снаряжением. Числом.\n\n"
    "Контрольное время — это не час, к которому надо успеть наверх. Это час, в который ты разворачиваешься "
    "и идёшь вниз. Дошёл ты или нет. Осталось три часа или двадцать минут.\n\n"
    "В прежние годы Холл называл час дня, иногда два. Запомните это число.\n\n"
    "Но в то утро оно не прозвучало.\n\n"
    "#РобХолл #Эверест #КонтрольноеВремя #Альпинизм #Правило #Безопасность #1996 #Shorts",

    "В два часа дня до вершины оставался час хода. Разворот стоил бы только денег "
    "и ещё одного года ожидания.\n\n"
    "В три часа Хансена догнал шерпа Анг Дордже и велел идти вниз. Ему за это и платят. "
    "Хансен не развернулся.\n\n"
    "Его догнал сам Холл, они коротко поговорили — и Хансен снова пошёл вверх.\n\n"
    "Третий раз был уже наверху, где спуск в темноте был не риском, а расписанием. "
    "К вечеру на гору легла буря.\n\n"
    "#Эверест #ДугласХансен #АнгДордже #РобХолл #Буря #1996 #Альпинизм #Решение #Shorts",

    "Искуситель приходит к Христу не в первый день поста. Он приходит на сороковой.\n\n"
    "Мара приходит к Будде не тогда, когда тот уходит из дворца, а в ночь перед самым прозрением. "
    "Ни разу в начале. Всегда у порога, где до конца рукой подать.\n\n"
    "В начале пути отступить почти ничего не стоит: вложено ещё немного, терять нечего. "
    "У порога отступить стоит всего сразу — двух лет, всех сбережений и той зимы, "
    "когда ты объяснял знакомым, что в прошлый раз не хватило совсем чуть-чуть.\n\n"
    "Шри Чинмой: «Сомнение бьёт сильнее всего у самого порога.»\n\n"
    "#Искушение #ШриЧинмой #Мара #Будда #СилаВоли #Сомнение #Путь #Философия #Shorts",

    "В восемь утра соблюсти контрольное время легко: до вершины ещё день пути, разворачиваться незачем. "
    "Дорого оно ровно один раз — в тот час, когда цель уже видна.\n\n"
    "Хансена нельзя было развернуть, и упрямство тут ни при чём. Он однажды отсюда уже разворачивался "
    "и целый год потом знал, как близко это было. Того, кто ни разу не подходил близко, повернуть можно. "
    "Того, кто год назад повернул, почти нельзя.\n\n"
    "От всей истории осталось одно число. На рассвете оно не стоило ничего, "
    "а к ночи стоило двух жизней.\n\n"
    "#Эверест #ЦенаРешения #1996 #ДугласХансен #РобХолл #Финал #КонтрольноеВремя #Shorts",

    "В три часа дня шерпа Анг Дордже догнал Хансена на склоне и сказал вслух то, что должен был сказать. "
    "Разворачивайся. Ему за это платят. За то, чтобы говорить это вслух.\n\n"
    "Хансен посмотрел на него и пошёл дальше вверх. Его догнал сам Холл, они коротко поговорили — "
    "и Хансен снова встал в цепочку.\n\n"
    "Анг Дордже развернулся и пошёл вниз. Он выжил.\n\n"
    "Голос, который слышен, но не слушается — это не тишина. Это самый громкий звук, какой вообще бывает на горе.\n\n"
    "#Эверест #АнгДордже #Шерпа #1996 #ГолосРазума #Альпинизм #Правило #Shorts",

    "Скотт Фишер водил свою группу — американскую фирму «Маунтин мэднесс». "
    "Как и Холл, он славился тем, что клиенты возвращаются. Как и Холл, он вышел на вершину поздно. "
    "Как и Холл, он не развернулся вовремя.\n\n"
    "Но было одно отличие: рядом с Фишером наверху не было никого, за кого он отвечал. "
    "Он был один. И именно поэтому он не смог спуститься.\n\n"
    "Два зеркала, два гида, одна ночь.\n\n"
    "#СкоттФишер #MountainMadness #Эверест #1996 #Зеркало #Альпинизм #Трагедия #Shorts",

    "Анатолий Букреев шёл на вершину без кислорода. Он вышел первым и спустился первым. "
    "В Лагере Четыре он уже отдыхал, когда понял: наверху остались люди.\n\n"
    "Он встал и пошёл обратно. В бурю. Без кислорода. Без связки. "
    "Нашёл троих и вывел их. Маклуглина. Хатчинсона. Фокс.\n\n"
    "Сам Букреев не дошёл до лагеря. Его нашли утром, в нескольких шагах от палатки.\n\n"
    "Правило говорит: останься в живых. Сердце говорит: иди обратно.\n\n"
    "#АнатолийБукреев #Эверест #1996 #Сострадание #Подвиг #Альпинизм #Спасение #Shorts",
]

TAGS_LIST = [
    ["Эверест", "Дуглас Хансен", "1996", "Роб Холл", "Гималаи", "альпинизм",
     "история", "почтальон", "трагедия на Эвересте", "Into Thin Air", "Джон Кракауэр", "горы"],
    ["Роб Холл", "Эверест", "контрольное время", "turn-around time", "альпинизм",
     "безопасность в горах", "1996", "экспедиция", "правило", "восьмитысячник"],
    ["Эверест", "Дуглас Хансен", "Анг Дордже", "Роб Холл", "шерпа", "буря",
     "1996", "альпинизм", "разворот", "вершина", "Гималаи", "трагедия"],
    ["искушение", "Шри Чинмой", "Мара", "Будда", "сомнение", "сила воли",
     "философия", "духовный путь", "гора", "Эверест", "испытание", "порог", "цель"],
    ["Эверест", "цена решения", "1996", "Дуглас Хансен", "Роб Холл", "финал",
     "контрольное время", "альпинизм", "трагедия", "Гималаи", "вершина"],
    ["Анг Дордже", "шерпа", "Эверест", "1996", "голос разума", "альпинизм",
     "правило", "разворот", "Хансен", "Гималаи", "свидетель"],
    ["Скотт Фишер", "Mountain Madness", "Эверест", "1996", "зеркало", "альпинизм",
     "гид", "трагедия", "Холл", "Гималаи", "смерть", "одиночество"],
    ["Анатолий Букреев", "Эверест", "1996", "сострадание", "подвиг", "альпинизм",
     "спасение", "буря", "без кислорода", "Холл", "Гималаи", "самопожертвование"],
]


def download_from_drive(file_id, out_path):
    """Download file from Google Drive using direct download URL."""
    url = f"https://drive.google.com/uc?export=download&id={file_id}"
    print(f"  Скачиваю {file_id}...", file=sys.stderr)
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = resp.read()
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(data)
    print(f"  Скачано: {len(data) / 1024 / 1024:.1f} МБ", file=sys.stderr)
    return out_path


def get_credentials():
    """Get OAuth2 credentials, refreshing or opening browser if needed."""
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r") as f:
            token_data = json.load(f)
        creds = Credentials(
            token=token_data.get("token"),
            refresh_token=token_data.get("refresh_token"),
            token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=token_data.get("client_id"),
            client_secret=token_data.get("client_secret"),
            scopes=SCOPES,
        )
        if creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            print("Токен истёк, обновляю...", file=sys.stderr)
            creds.refresh(Request())
            _save_token(creds)
        return creds

    # First time: open browser for OAuth
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET, SCOPES)
    print("Открываю браузер для авторизации...", file=sys.stderr)
    creds = flow.run_local_server(port=0)
    _save_token(creds)
    return creds


def _save_token(creds):
    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
    }
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    with open(TOKEN_FILE, "w") as f:
        json.dump(token_data, f, indent=2)
    # Remove write permissions so it's not accidentally committed
    os.chmod(TOKEN_FILE, 0o600)
    print("Токен сохранён: " + TOKEN_FILE, file=sys.stderr)


def build_service(creds):
    from googleapiclient.discovery import build
    return build("youtube", "v3", credentials=creds)


def upload_video(youtube, file_path, title, description, tags, category_id="27",
                 scheduled_time=None):
    """Upload a single video to YouTube. If scheduled_time is set, publish as private with publishAt."""
    from googleapiclient.http import MediaFileUpload

    if scheduled_time:
        status = {
            "privacyStatus": "private",
            "selfDeclaredMadeForKids": False,
            "publishAt": scheduled_time,  # ISO 8601 format
        }
    else:
        status = {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        }

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": category_id,  # 27 = Education
        },
        "status": status,
    }

    media = MediaFileUpload(file_path, mimetype="video/mp4", resumable=True)
    print(f"  Загружаю: {os.path.basename(file_path)} ({os.path.getsize(file_path) / 1024 / 1024:.1f} МБ)",
          file=sys.stderr)

    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            print(f"\r  Прогресс: {pct}%", end="", file=sys.stderr, flush=True)

    print(file=sys.stderr)  # newline after progress
    video_id = response["id"]
    video_url = f"https://youtube.com/watch?v={video_id}"
    print(f"  ✅ Опубликовано: {video_url}", file=sys.stderr)
    return video_id, video_url


def main():
    args = sys.argv[1:]
    peel_dir = os.path.join(ROOT, "narrated-shorts", SERIES, "peel")

    if "--auth" in args:
        creds = get_credentials()
        print("Авторизация успешна! Токен сохранён.", file=sys.stderr)
        return

    if "--list" in args:
        import glob
        for i, title in enumerate(TITLES, 1):
            # Find local file (peel or output)
            matches = []
            for d in [peel_dir, OUTPUT_DIR]:
                if os.path.isdir(d):
                    matches.extend(glob.glob(os.path.join(d, f"short-{i:02d}-*.mp4")))
            if matches:
                status = f"локально: {os.path.basename(matches[0])}"
            elif i <= len(DRIVE_FILE_IDS):
                status = "только Drive"
            else:
                status = "❌ не найдено"
            drive_info = f"\n     Drive: {DRIVE_FILE_IDS[i-1]}" if i <= len(DRIVE_FILE_IDS) else ""
            print(f"  {i}. {title}\n     {status}{drive_info}")
        return

    # Upload mode
    creds = get_credentials()
    youtube = build_service(creds)

    total_eps = len(TITLES)

    if "--upload-all" in args:
        indices = list(range(total_eps))
    elif "--upload" in args:
        idx = int(args[args.index("--upload") + 1]) - 1
        indices = [idx]
    else:
        print("Usage: --auth | --upload-all | --upload N | --list", file=sys.stderr)
        return

    # Use local peel videos if available, otherwise download from Drive

    for i in indices:
        print(f"\n=== Эпизод {i + 1}/{total_eps} ===", file=sys.stderr)

        # Find local peel video (eps 1-5) or output video (eps 6+)
        local_path = None

        # Try peel dir first (eps 1-5)
        for f in os.listdir(peel_dir) if os.path.isdir(peel_dir) else []:
            if f.startswith(f"short-{i+1:02d}-") and f.endswith("-peel.mp4"):
                local_path = os.path.join(peel_dir, f)
                break

        # Try output dir (eps 6+ or fallback)
        if not local_path:
            for f in os.listdir(OUTPUT_DIR) if os.path.isdir(OUTPUT_DIR) else []:
                if f.startswith(f"short-{i+1:02d}-") and f.endswith(".mp4"):
                    local_path = os.path.join(OUTPUT_DIR, f)
                    break

        if not local_path:
            # Fallback: download from Drive (only eps 1-5 have Drive IDs)
            if i < len(DRIVE_FILE_IDS):
                file_id = DRIVE_FILE_IDS[i]
                tmp_dir = os.path.join(ROOT, "tools", ".tmp_uploads")
                os.makedirs(tmp_dir, exist_ok=True)
                local_path = os.path.join(tmp_dir, f"ep{i+1}.mp4")
                if not os.path.exists(local_path):
                    download_from_drive(file_id, local_path)
            else:
                print(f"  ❌ Видео для эпизода {i+1} не найдено!", file=sys.stderr)
                continue

        # Scheduled publish: Sep 10-17, 2026, 10:00 Almaty (04:00 UTC)
        schedule_dates = [
            "2026-09-10", "2026-09-11", "2026-09-12", "2026-09-13", "2026-09-14",
            "2026-09-15", "2026-09-16", "2026-09-17",
        ]
        sched = f"{schedule_dates[i]}T04:00:00Z"

        video_id, url = upload_video(
            youtube, local_path,
            title=TITLES[i],
            description=DESCRIPTIONS[i],
            tags=TAGS_LIST[i],
            scheduled_time=sched,
        )
        print(f"\n  Эпизод {i+1}: {url}  (запланирован: {schedule_dates[i]})\n")
        if i < max(indices):
            print("  Пауза 5 сек...", file=sys.stderr)
            time.sleep(5)

    print("\n✅ Все эпизоды загружены и запланированы!", file=sys.stderr)


if __name__ == "__main__":
    main()
