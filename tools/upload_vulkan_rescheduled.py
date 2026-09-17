#!/usr/bin/env python3
"""
upload_vulkan_rescheduled.py — Re-upload deleted «Последний вулкан» episodes with optimized descriptions.

Episodes rescheduled for October 2026:
  - Ep 3: "Правило было под рукой — трижды" → Oct 13
  - Ep 5: "Что стоило это число?" → Oct 15

Usage:
  python tools/upload_vulkan_rescheduled.py --upload-all
  python tools/upload_vulkan_rescheduled.py --upload 3
"""
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERIES = "posledniy-vulkan-shorts"
SERIES_DIR = os.path.join(ROOT, "narrated-shorts", SERIES)
OUTPUT_DIR = os.path.join(SERIES_DIR, "output")
TOKEN_FILE = os.path.join(ROOT, "tools", "youtube_token.json")

SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube"]

# Episodes to re-upload with optimized descriptions
RESCHEDULED = {
    3: {
        "title": "Правило было под рукой — трижды",
        "description": (
            "В два часа дня до вершины оставался час хода. Разворот стоил бы только денег "
            "и ещё одного года ожидания.\n\n"
            "В три часа Хансена догнал шерпа Анг Дордже и велел идти вниз. Ему за это и платят. "
            "Хансен не развернулся.\n\n"
            "Его догнал сам Холл, они коротко поговорили — и Хансен снова пошёл вверх.\n\n"
            "Третий раз был уже наверху, где спуск в темноте был не риском, а расписанием. "
            "К вечеру на гору легла буря.\n\n"
            "Серия «Последний вулкан» · Эверест 1996\n"
            "Основано на реальных событиях трагедии на Эвересте\n\n"
            "#Эверест #ДугласХансен #АнгДордже #РобХолл #1996 #Альпинизм #Трагедия #shorts"
        ),
        "tags": ["Эверест", "Дуглас Хансен", "Анг Дордже", "Роб Холл", "шерпа", "буря",
                 "1996", "альпинизм", "разворот", "вершина", "Гималаи", "трагедия"],
        "publish_date": "2026-10-13T04:00:00Z",
    },
    5: {
        "title": "Одно число стоило две жизни",
        "description": (
            "В восемь утра соблюсти контрольное время легко: до вершины ещё день пути, "
            "разворачиваться незачем. Дорого оно ровно один раз — в тот час, когда цель уже видна.\n\n"
            "Хансена нельзя было развернуть, и упрямство тут ни при чём. Он однажды отсюда уже "
            "разворачивался и целый год потом знал, как близко это было. Того, кто ни разу не "
            "подходил близко, повернуть можно. Того, кто год назад повернул, почти нельзя.\n\n"
            "Серия «Последний вулкан» · Эверест 1996\n"
            "Основано на реальных событиях трагедии на Эвересте\n\n"
            "#Эверест #ЦенаРешения #1996 #ДугласХансен #РобХолл #КонтрольноеВремя #Альпинизм #shorts"
        ),
        "tags": ["Эверест", "цена решения", "1996", "Дуглас Хансен", "Роб Холл", "финал",
                 "контрольное время", "альпинизм", "трагедия", "Гималаи", "вершина"],
        "publish_date": "2026-10-15T04:00:00Z",
    },
}


def get_credentials():
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
            creds.refresh(Request())
        return creds

    flow = InstalledAppFlow.from_client_secrets_file(
        os.path.join(ROOT, "tools", "client_secret.json"), SCOPES
    )
    creds = flow.run_local_server(port=0)
    return creds


def build_service(creds):
    from googleapiclient.discovery import build
    return build("youtube", "v3", credentials=creds)


def upload_video(youtube, file_path, title, description, tags, scheduled_time):
    from googleapiclient.http import MediaFileUpload

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "27",
        },
        "status": {
            "privacyStatus": "private",
            "selfDeclaredMadeForKids": False,
            "publishAt": scheduled_time,
        },
    }

    media = MediaFileUpload(file_path, mimetype="video/mp4", resumable=True)
    print(f"  Загружаю: {os.path.basename(file_path)}", file=sys.stderr)

    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            print(f"\r  Прогресс: {pct}%", end="", file=sys.stderr, flush=True)

    print(file=sys.stderr)
    video_id = response["id"]
    return video_id, f"https://youtube.com/watch?v={video_id}"


def main():
    args = sys.argv[1:]

    if "--upload-all" in args:
        indices = sorted(RESCHEDULED.keys())
    elif "--upload" in args:
        idx = int(args[args.index("--upload") + 1])
        indices = [idx]
    else:
        print("Usage: --upload-all | --upload N", file=sys.stderr)
        return

    creds = get_credentials()
    youtube = build_service(creds)

    for i in indices:
        if i not in RESCHEDULED:
            print(f"  ❌ Эпизод {i} не в списке перенесённых!", file=sys.stderr)
            continue

        print(f"\n=== Эпизод {i} ===", file=sys.stderr)
        data = RESCHEDULED[i]

        # Find local file
        local_path = None
        for f in os.listdir(OUTPUT_DIR):
            if f.startswith(f"short-{i:02d}-") and f.endswith(".mp4"):
                local_path = os.path.join(OUTPUT_DIR, f)
                break

        if not local_path:
            print(f"  ❌ Видео для эпизода {i} не найдено!", file=sys.stderr)
            continue

        video_id, url = upload_video(
            youtube, local_path,
            title=data["title"],
            description=data["description"],
            tags=data["tags"],
            scheduled_time=data["publish_date"],
        )
        print(f"\n  ✅ Эпизод {i}: {url}  (запланирован: {data['publish_date'][:10]})\n")

        if i < max(indices):
            time.sleep(5)

    print("\n✅ Все перенесённые эпизоды загружены!", file=sys.stderr)


if __name__ == "__main__":
    main()
