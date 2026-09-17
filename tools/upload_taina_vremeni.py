#!/usr/bin/env python3
"""
upload_taina_vremeni.py — Upload «Тайна времени» series to YouTube.

Usage:
  python tools/upload_taina_vremeni.py --auth          # First time: OAuth browser login
  python tools/upload_taina_vremeni.py --upload-all    # Upload all 5 episodes
  python tools/upload_taina_vremeni.py --upload 1      # Upload episode 1 only
  python tools/upload_taina_vremeni.py --list          # Show queued episodes with status

OAuth token is saved to tools/youtube_token.json (gitignored).
Credentials: tools/client_secret.json
Episodes: narrated-shorts/taina-vremeni-shorts/scripts.json
Videos:   narrated-shorts/taina-vremeni-shorts/output/
"""
import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERIES = "taina-vremeni-shorts"
SERIES_DIR = os.path.join(ROOT, "narrated-shorts", SERIES)
SCRIPTS = os.path.join(SERIES_DIR, "scripts.json")
OUTPUT_DIR = os.path.join(SERIES_DIR, "output")
CLIENT_SECRET = os.path.join(ROOT, "tools", "client_secret.json")
TOKEN_FILE = os.path.join(ROOT, "tools", "youtube_token.json")

SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube"]

TITLES = [
    "Каждый день вы убиваете время. А время убивает вас",
    "Есть секунда, в которую умещается вся жизнь",
    "Час с любимым пролетает как мгновение. Час в очереди — как вечность",
    "Мы живём так, будто впереди бесконечность",
    "Мы столько лет воюем со временем",
]

DESCRIPTIONS = [
    "Каждый день вы убиваете время. А время убивает вас — каждый день. Мы говорим «убить время» и не замечаем, что произносим древнее заклинание. Физик Альберт писал: время — самая демократичная валюта во вселенной. Каждый получает ровно 86 400 секунд в сутки. Но парадокс: тот, кто пытается сэкономить время, тратит его больше всех.\n\n"
    "Шри Чинмой увидел это зеркало: время — единственное, что человек пытается убить, и единственное, что в итоге убивает его.\n\n"
    "Серия 1/5 · «Тайна времени»\nОсновано на книге Шри Чинмоя «Земное время и вечное время»\n\n"
    "#ШриЧинмой #Время #Философия #Осознанность #ТайнаВремени #ShriChinmoy #shorts",

    "Есть секунда, в которую умещается вся жизнь. А есть секунды, пустые, как высохший колодец, — и они тянутся годами. Физика знает: секунда — это 9 миллиардов колебаний цезиевых атомов. Но душа ведёт свой счёт. Секунда, когда отец впервые взял ребёнка на руки. Секунда перед ударом, когда время сгущается и замирает.\n\n"
    "Шри Чинмой различал два времени: хронологическое и психологическое. Первое движется равномерно, как поезд по расписанию. Второе прыгает, поётся, молчит — и в одной своей ноте вмещает то, на что у первого не хватило бы века.\n\n"
    "Серия 2/5 · «Тайна времени»\nОсновано на книге Шри Чинмоя «Земное время и вечное время»\n\n"
    "#ШриЧинмой #Вечность #Мгновение #Философия #Осознанность #ТайнаВремени #shorts",

    "Вы замечали, как час с любимым человеком пролетает за одно мгновение, а час в очереди растягивается в бесконечность? Психологи называют это субъективным временем — внутренней скоростью, с которой сознание проживает каждую секунду. Когда мозг захвачен новым, он записывает больше кадров на единицу времени. Рутина, напротив, схлопывает дни в один длинный смазанный кадр.\n\n"
    "Шри Чинмой шёл дальше психологии и говорил, что не только восприятие, но и само качество внимания определяет, сколько времени вмещает момент.\n\n"
    "Серия 3/5 · «Тайна времени»\nОсновано на книге Шри Чинмоя «Земное время и вечное время»\n\n"
    "#ШриЧинмой #СубъективноеВремя #Восприятие #Философия #Осознанность #ТайнаВремени #shorts",

    "Мы живём так, будто впереди бесконечность, и боимся даже подумать о том, что она однажды закончится. Экзистенциалисты называли это пограничной ситуацией — момент, когда привычная броня повседневности трескается и человек вдруг понимает, что дни сочтены. Диагноз, потеря, внезапная близость конца.\n\n"
    "И парадокс в том, что именно это знание делает жизнь живой. Шри Чинмой говорил, что мысль о смерти — не пугало, а учитель: она не отнимает у нас время, а возвращает его нам.\n\n"
    "Серия 4/5 · «Тайна времени»\nОсновано на книге Шри Чинмоя «Земное время и вечное время»\n\n"
    "#ШриЧинмой #Смерть #Жизнь #Философия #Осознанность #ТайнаВремени #Экзистенциализм #shorts",

    "Мы столько лет воюем со временем — торопимся, опаздываем, догоняем, и даже не замечаем, как эта война делает нас уставшими и пустыми. Шри Чинмой говорил, что есть момент, когда человек перестаёт бороться со временем и начинает с ним дружить. И в этот момент происходит нечто странное: время перестает быть врагом.\n\n"
    "Оно больше не давит, не торопит, не уходит. Оно становится пространством, в котором можно дышать. Когда вы перестаёте считать секунды, они перестают считать вас.\n\n"
    "Серия 5/5 · «Тайна времени»\nОсновано на книге Шри Чинмоя «Земное время и вечное время»\n\n"
    "#ШриЧинмой #ДружбаСоВременем #Принятие #Философия #Осознанность #ТайнаВремени #shorts",
]

TAGS_LIST = [
    ["Шри Чинмой", "время", "философия", "осознанность", "медитация",
     "Тайна времени", "Shri Chinmoy", "убить время", "86400 секунд", "жизнь"],
    ["Шри Чинмой", "вечность", "мгновение", "секунда", "философия",
     "осознанность", "Тайна времени", "Shri Chinmoy", "хронологическое время", "психологическое время"],
    ["Шри Чинмой", "субъективное время", "восприятие", "психология", "философия",
     "осознанность", "Тайна времени", "Shri Chinmoy", "внимание", "момент"],
    ["Шри Чинмой", "смерть", "жизнь", "экзистенциализм", "философия",
     "осознанность", "Тайна времени", "Shri Chinmoy", "пограничная ситуация", "конечность"],
    ["Шри Чинмой", "дружба со временем", "принятие", "философия", "осознанность",
     "Тайна времени", "Shri Chinmoy", "борьба", "покой", "настоящий момент"],
]


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
            "publishAt": scheduled_time,
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
            "categoryId": category_id,
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

    print(file=sys.stderr)
    video_id = response["id"]
    video_url = f"https://youtube.com/watch?v={video_id}"
    print(f"  ✅ Опубликовано: {video_url}", file=sys.stderr)
    return video_id, video_url


def main():
    args = sys.argv[1:]
    peel_dir = os.path.join(SERIES_DIR, "peel")

    if "--auth" in args:
        creds = get_credentials()
        print("Авторизация успешна! Токен сохранён.", file=sys.stderr)
        return

    if "--list" in args:
        import glob
        for i, title in enumerate(TITLES, 1):
            matches = []
            for d in [peel_dir, OUTPUT_DIR]:
                if os.path.isdir(d):
                    matches.extend(glob.glob(os.path.join(d, f"short-{i:02d}-*.mp4")))
            if matches:
                status = f"локально: {os.path.basename(matches[0])}"
            else:
                status = "❌ не найдено"
            print(f"  {i}. {title}\n     {status}")
        return

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

    for i in indices:
        print(f"\n=== Эпизод {i + 1}/{total_eps} ===", file=sys.stderr)

        local_path = None
        for d in [peel_dir, OUTPUT_DIR]:
            if os.path.isdir(d):
                for f in os.listdir(d):
                    if f.startswith(f"short-{i+1:02d}-") and f.endswith(".mp4"):
                        local_path = os.path.join(d, f)
                        break
            if local_path:
                break

        if not local_path:
            print(f"  ❌ Видео для эпизода {i+1} не найдено!", file=sys.stderr)
            continue

        # Scheduled publish: October 14, 16, 18, 20, 22, 2026, 10:00 Almaty (04:00 UTC)
        schedule_dates = [
            "2026-10-14", "2026-10-16", "2026-10-18", "2026-10-20", "2026-10-22",
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
