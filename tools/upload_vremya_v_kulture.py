#!/usr/bin/env python3
"""
upload_vremya_v_kulture.py — Upload «Время в культуре» series to YouTube.

Usage:
  python tools/upload_vremya_v_kulture.py --auth          # First time: OAuth browser login
  python tools/upload_vremya_v_kulture.py --upload-all    # Upload all 10 episodes now
  python tools/upload_vremya_v_kulture.py --upload 1      # Upload episode 1 only
  python tools/upload_vremya_v_kulture.py --schedule-all  # Schedule all 10 episodes in 1 year
  python tools/upload_vremya_v_kulture.py --create-playlist  # Create playlist
  python tools/upload_vremya_v_kulture.py --list          # Show queued episodes with status

OAuth token is saved to tools/youtube_token.json (gitignored).
Credentials: tools/client_secret.json
Episodes: narrated-shorts/vremya-v-kulture-shorts/scripts.json
Videos:   narrated-shorts/vremya-v-kulture-shorts/output/
"""
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERIES = "vremya-v-kulture-shorts"
SERIES_DIR = os.path.join(ROOT, "narrated-shorts", SERIES)
SCRIPTS = os.path.join(SERIES_DIR, "scripts.json")
OUTPUT_DIR = os.path.join(SERIES_DIR, "output")
CLIENT_SECRET = os.path.join(ROOT, "tools", "client_secret.json")
TOKEN_FILE = os.path.join(ROOT, "tools", "youtube_token.json")

SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube"]

TITLES = [
    "Древние египтяне знали два слова для вечности",
    "Древние греки имели два слова для времени",
    "В индуизме время - не линия. Это колесо",
    "Будда сказал: всё возникает и исчезает",
    "Майя не считали время. Они его слышали",
    "В древнем Китае время принадлежало Небу",
    "Стоики: время - единственное, что ваше",
    "В средневековье время принадлежало Богу",
    "В 14 веке появились часы. И всё изменилось",
    "Мы потеряли время. И вот как его вернуть",
]

DESCRIPTIONS = [
    "Пять тысяч лет назад, когда фараоны строили пирамиды, жрецы Гелиополя различали нехе иджет. Нехе - время циклическое: восход и закат, разлив Нила, смена сезонов. Время, которое возвращается. Джет - время статичное: вечность мёртвых, неизменность камня, абсолют за пределами перемен.\n\n"
    "Египтяне не выбирали между ними. Они видели: полная картина времени требует обоих. Шри Чинмой говорил похожее: земное время - необходимость, небесное время - реальность. Истина - в их встрече.\n\n"
    "Серия 1/10 · «Время в культуре»\nОсновано на работах Шри Чинмоя из https://www.srichinmoylibrary.com/\n\n"
    "#ШриЧинмой #ДревнийЕгипет #Вечность #Философия #Осознанность #ВремяВКультуре #shorts",

    "Афинские философы различали хронос и кайрос. Хронос - время количественное: секунды, минуты, часы. Кайрос - время качественное: подходящий момент, мгновение истины. Хронос спрашивает: сколько времени прошло? Кайрос спрашивает: пришло ли время?\n\n"
    "Аристотель говорил: если ты ждёшь или медлишь, этот момент уйдёт навсегда. Шри Чинмой шёл дальше: в одно мгновение времени души можно достичь того, на что в земном времени нужны часы.\n\n"
    "Серия 2/10 · «Время в культуре»\nОсновано на работах Шри Чинмоя из https://www.srichinmoylibrary.com/\n\n"
    "#ШриЧинмой #ДревняяГреция #Хронос #Кайрос #Философия #ВремяВКультуре #shorts",

    "Древние ведические мудрецы видели время как вечное возвращение. Четыре юги вращаются бесконечно. Калачакра - Колесо Времени - учит: каждый момент содержит все эпохи одновременно. Вопрос не в том, когда вы живёте. Вопрос в том, где внутри колеса вы находитесь.\n\n"
    "Шри Чинмой говорил: мы живём не в земном времени - мы живём в вечности. Вечность имеет прошлое, настоящее и будущее. Колесо крутится не для того, чтобы вернуться к началу. А чтобы каждый круг поднимал нас выше.\n\n"
    "Серия 3/10 · «Время в культуре»\nОсновано на работах Шри Чинмоя из https://www.srichinmoylibrary.com/\n\n"
    "#ШриЧинмой #Индуизм #Калачакра #Юги #Философия #ВремяВКультуре #shorts",

    "Аничча - непостоянство - первое из трёх признаков существования в буддизме. Всё, что рождено, умрёт. Но это не повод для отчаяния. Это причина для пробуждения. Когда вы действительно понимаете, что этот момент не повторится, он становится драгоценным.\n\n"
    "Дзен-мастера говорили: не ищите вечность вне времени. Вечность - в полном присутствии внутри преходящего. Шри Чинмой учил: когда живёшь в душе, нет такой вещи, как смерть. Не потому что тело вечно. А потому что душа знает: каждое мгновение - это вечность, сжатая до точки.\n\n"
    "Серия 4/10 · «Время в культуре»\nОсновано на работах Шри Чинмоя из https://www.srichinmoylibrary.com/\n\n"
    "#ШриЧинмой #Буддизм #Непостоянство #Дзен #Философия #ВремяВКультуре #shorts",

    "Цолькин - священный календарь майя - состоял из 260 дней. Это время человеческой беременности. Двадцать имён дней, тринадцать чисел, вращающихся вместе. Майя не видели время как стрелу. Они видели его как спираль, возвращающуюся, но каждый раз на другом уровне.\n\n"
    "Время было не абстракцией - оно было живым. Каждый день нёс свою энергию, свою задачу, свою молитву. Шри Чинмой говорил: время - это любовь. Если мы любим время, оно даёт нам то, что нужно: радость. Майя любили время настолько, что превратили его в музыку.\n\n"
    "Серия 5/10 · «Время в культуре»\nОсновано на работах Шри Чинмоя из https://www.srichinmoylibrary.com/\n\n"
    "#ШриЧинмой #Майя #Цолькин #Календарь #Философия #ВремяВКультуре #shorts",

    "Китайские императорские астрономы вели календарь не для удобства - для сохранения космического порядка. Лунно-солнечный календарь следил за двумя ритмами одновременно. Время было не линейным прогрессом, а гармонией. Конфуций говорил: Небо говорит не словами, но через времена и природу.\n\n"
    "Шри Чинмой учил: Всевышний в нас, Внутренний Кормчий, исполняет Свою мечту и Свою реальность здесь на земле через время. Время - не враг, которого нужно победить. Время - партнёр, с которым нужно танцевать.\n\n"
    "Серия 6/10 · «Время в культуре»\nОсновано на работах Шри Чинмоя из https://www.srichinmoylibrary.com/\n\n"
    "#ШриЧинмой #ДревнийКитай #Гармония #Философия #Осознанность #ВремяВКультуре #shorts",

    "Сенека написал трактат «О скоротечности жизни». Его тезис: жизнь не коротка - мы сами её сокращаем. Марк Аврелий каждый вечер спрашивал: что я сделал с этим днём? Эпиктет шёл дальше: мы не владеем ничем, кроме этого момента.\n\n"
    "Шри Чинмой согласился бы: он различал земное время, которое можно потратить, и время души, которое можно только наполнить. Когда вы смотрите внутрь, вы экономите время. Когда смотрите назад, вы его тратите. Стоики знали это две тысячи лет назад.\n\n"
    "Серия 7/10 · «Время в культуре»\nОсновано на работах Шри Чинмоя из https://www.srichinmoylibrary.com/\n\n"
    "#ШриЧинмой #Стоицизм #Сенека #МаркАврелий #Философия #ВремяВКультуре #shorts",

    "Бенедиктинский устав разделил день на семь канонических часов. Не потому что Бог нуждался в напоминаниях. А потому что человек нуждался в ритме. Каждый час - не прерывание работы, а возвращение к центру. Монахи не считали время - они его освящали.\n\n"
    "Средневековые соборы строились столетиями. Архитектор, закладывавший фундамент, никогда не видел завершения. Но это было актом веры: время больше, чем одна жизнь. Шри Чинмой говорил: сегодняшняя НЕВОЗМОЖНОСТЬ становится завтрашним достижением.\n\n"
    "Серия 8/10 · «Время в культуре»\nОсновано на работах Шри Чинмоя из https://www.srichinmoylibrary.com/\n\n"
    "#ШриЧинмой #Средневековье #Монастыри #Философия #Осознанность #ВремяВКультуре #shorts",

    "До изобретения часового механизма время было публичным достоянием. Солнце принадлежало всем. Потом, в четырнадцатом веке, появились первые башенные часы. И время стало собственностью. Купцы могли измерить, сколько стоит час работы.\n\n"
    "Это была революция, тихая, но тотальная. Мы перестали спрашивать «который час?» у природы. Мы начали спрашивать у механизма. Шри Чинмой предупреждал: земное время измеряет все наши действия и само может быть измерено. Но душа использует безграничное время.\n\n"
    "Серия 9/10 · «Время в культуре»\nОсновано на работах Шри Чинмоя из https://www.srichinmoylibrary.com/\n\n"
    "#ШриЧинмой #ИсторияВремени #Часы #Философия #Осознанность #ВремяВКультуре #shorts",

    "Пять тысяч лет цивилизация учила нас измерять время. Египтяне дали нам циклы и вечность. Греки - качество момента. Индусы - колесо возвращения. Буддисты - красоту непостоянства. Майя - священную музыку дней. И вот мы здесь - с атомными часами и самыми заполненными расписаниями в истории.\n\n"
    "Шри Чинмой сказал простую вещь: выбрать время - значит спасти время. Мы можем выбрать время, любя время. Не измеряя его. Не оптимизируя его. Любя его. Каждый момент - не единица производства. Это встреча. Время ждёт не календаря. Оно ждёт внимания.\n\n"
    "Серия 10/10 · «Время в культуре» (финал)\nОсновано на работах Шри Чинмоя из https://www.srichinmoylibrary.com/\n\n"
    "#ШриЧинмой #Время #Любовь #Философия #Осознанность #ВремяВКультуре #shorts",
]

TAGS_LIST = [
    ["Шри Чинмой", "Древний Египет", "вечность", "философия", "осознанность",
     "Время в культуре", "Shri Chinmoy", "нехе", "джет", "циклическое время"],
    ["Шри Чинмой", "Древняя Греция", "хронос", "кайрос", "философия",
     "Время в культуре", "Shri Chinmoy", "Аристотель", "Платон", "момент"],
    ["Шри Чинмой", "индуизм", "Калачакра", "юги", "философия",
     "Время в культуре", "Shri Chinmoy", "колесо времени", "циклы", "вечность"],
    ["Шри Чинмой", "буддизм", "непостоянство", "дзен", "философия",
     "Время в культуре", "Shri Chinmoy", "аничча", "момент", "присутствие"],
    ["Шри Чинмой", "Майя", "Цолькин", "календарь", "философия",
     "Время в культуре", "Shri Chinmoy", "священное время", "циклы", "гармония"],
    ["Шри Чинмой", "Древний Китай", "гармония", "философия", "осознанность",
     "Время в культуре", "Shri Chinmoy", "Конфуций", "Небо", "ритм"],
    ["Шри Чинмой", "стоицизм", "Сенека", "Марк Аврелий", "философия",
     "Время в культуре", "Shri Chinmoy", "Эпиктет", "настоящий момент", "богатство"],
    ["Шри Чинмой", "средневековье", "монастыри", "философия", "осознанность",
     "Время в культуре", "Shri Chinmoy", "НЕВОЗМОЖНОСТЬ", "ритм", "вера"],
    ["Шри Чинмой", "история времени", "часы", "философия", "осознанность",
     "Время в культуре", "Shri Chinmoy", "революция", "механическое время", "душа"],
    ["Шри Чинмой", "время", "любовь", "философия", "осознанность",
     "Время в культуре", "Shri Chinmoy", "выбор", "внимание", "встреча"],
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

    print(f"Загружаю: {title}", file=sys.stderr)
    request = youtube.videos().insert(part=",".join(body.keys()), body=body, media_body=media)
    response = None
    while response is None:
        status_code, progress = request.next_chunk()
        if status_code:
            print(f"  Загружено {int(status_code.progress())}%", file=sys.stderr)

    video_id = response["id"]
    print(f"✓ Видео загружено: {video_id}", file=sys.stderr)
    return video_id


def create_playlist(youtube, title, description, privacy="public"):
    """Create a new YouTube playlist."""
    body = {
        "snippet": {
            "title": title,
            "description": description,
        },
        "status": {
            "privacyStatus": privacy,
        },
    }

    print(f"Создаю плейлист: {title}", file=sys.stderr)
    response = youtube.playlists().insert(part=",".join(body.keys()), body=body).execute()
    playlist_id = response["id"]
    print(f"✓ Плейлист создан: {playlist_id}", file=sys.stderr)
    return playlist_id


def add_to_playlist(youtube, playlist_id, video_id):
    """Add a video to a playlist."""
    body = {
        "snippet": {
            "playlistId": playlist_id,
            "resourceId": {
                "kind": "youtube#video",
                "videoId": video_id,
            },
        },
    }

    request = youtube.playlistItems().insert(part=",".join(body.keys()), body=body)
    response = request.execute()
    print(f"✓ Видео {video_id} добавлено в плейлист {playlist_id}", file=sys.stderr)
    return response["id"]


def main():
    if "--auth" in sys.argv:
        get_credentials()
        print("Авторизация завершена.", file=sys.stderr)
        return

    creds = get_credentials()
    youtube = build_service(creds)

    if "--create-playlist" in sys.argv:
        playlist_id = create_playlist(
            youtube,
            "Время в культуре",
            "Серия из 10 роликов о том, как разные цивилизации понимали время. "
            "Основано на работах Шри Чинмоя.\n\n"
            "https://www.srichinmoylibrary.com/",
            privacy="public"
        )
        print(f"\nPlaylist ID: {playlist_id}")
        print("Сохраните этот ID для добавления видео.")
        return

    if "--upload-all" in sys.argv:
        video_ids = []
        for i in range(10):
            ep_num = i + 1
            slug = json.load(open(SCRIPTS))[i]["slug"]
            file_path = os.path.join(OUTPUT_DIR, f"short-{ep_num:02d}-{slug}.mp4")

            if not os.path.exists(file_path):
                print(f"⚠ Файл не найден: {file_path}", file=sys.stderr)
                continue

            video_id = upload_video(
                youtube,
                file_path,
                TITLES[i],
                DESCRIPTIONS[i],
                TAGS_LIST[i],
            )
            video_ids.append(video_id)
            time.sleep(2)  # Rate limiting

        print(f"\n✓ Загружено {len(video_ids)} видео")
        if video_ids:
            print(f"Video IDs: {video_ids}")
        return

    if "--schedule-all" in sys.argv:
        # Schedule all episodes in 1 year from now
        start_date = datetime.now() + timedelta(days=365)
        video_ids = []

        for i in range(10):
            ep_num = i + 1
            slug = json.load(open(SCRIPTS))[i]["slug"]
            file_path = os.path.join(OUTPUT_DIR, f"short-{ep_num:02d}-{slug}.mp4")

            if not os.path.exists(file_path):
                print(f"⚠ Файл не найден: {file_path}", file=sys.stderr)
                continue

            # Schedule every 2 days starting from 1 year from now
            scheduled_time = start_date + timedelta(days=i * 2)
            scheduled_time_str = scheduled_time.strftime("%Y-%m-%dT10:00:00.0Z")

            video_id = upload_video(
                youtube,
                file_path,
                TITLES[i],
                DESCRIPTIONS[i],
                TAGS_LIST[i],
                scheduled_time=scheduled_time_str,
            )
            video_ids.append(video_id)
            print(f"  Запланировано: {scheduled_time_str}")
            time.sleep(2)  # Rate limiting

        print(f"\n✓ Запланировано {len(video_ids)} видео через год")
        if video_ids:
            print(f"Video IDs: {video_ids}")
        return

    if "--upload" in sys.argv:
        idx = sys.argv.index("--upload")
        if idx + 1 >= len(sys.argv):
            print("Использование: --upload <номер_эпизода>", file=sys.stderr)
            sys.exit(1)

        ep_num = int(sys.argv[idx + 1])
        if ep_num < 1 or ep_num > 10:
            print("Номер эпизода должен быть от 1 до 10", file=sys.stderr)
            sys.exit(1)

        slug = json.load(open(SCRIPTS))[ep_num - 1]["slug"]
        file_path = os.path.join(OUTPUT_DIR, f"short-{ep_num:02d}-{slug}.mp4")

        if not os.path.exists(file_path):
            print(f"⚠ Файл не найден: {file_path}", file=sys.stderr)
            sys.exit(1)

        video_id = upload_video(
            youtube,
            file_path,
            TITLES[ep_num - 1],
            DESCRIPTIONS[ep_num - 1],
            TAGS_LIST[ep_num - 1],
        )
        print(f"\n✓ Видео загружено: {video_id}")
        return

    if "--list" in sys.argv:
        with open(SCRIPTS) as f:
            scripts = json.load(f)
        for i, ep in enumerate(scripts):
            ep_num = i + 1
            slug = ep["slug"]
            file_path = os.path.join(OUTPUT_DIR, f"short-{ep_num:02d}-{slug}.mp4")
            status = "✓" if os.path.exists(file_path) else "✗"
            print(f"{status} Эпизод {ep_num}: {slug}")
        return

    print("Использование:", file=sys.stderr)
    print("  --auth              Авторизация OAuth", file=sys.stderr)
    print("  --upload-all        Загрузить все 10 эпизодов сейчас", file=sys.stderr)
    print("  --schedule-all      Запланировать все 10 эпизодов через год", file=sys.stderr)
    print("  --create-playlist   Создать плейлист", file=sys.stderr)
    print("  --upload N          Загрузить эпизод N", file=sys.stderr)
    print("  --list              Показать список эпизодов", file=sys.stderr)


if __name__ == "__main__":
    main()
