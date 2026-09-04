#!/usr/bin/env python3
"""
post_telegram.py — публикация готового ролика (или текста) в Telegram-канал.

Telegram Bot API бесплатный: не нужен ни Publer, ни Metricool. Боту нужны права
администратора в канале.

Usage:
  python tools/post_telegram.py --video narrated-shorts/x/output/ep-01.mp4 \
      --caption-file narrated-shorts/x/caption-01.txt --yes
  python tools/post_telegram.py --text "..." --yes
  python tools/post_telegram.py --check                 # кто бот и куда он пишет
  python tools/post_telegram.py --video x.mp4 --caption "..."   # без --yes = сухой прогон

  --photo P        отправить картинку вместо видео
  --channel @name  перекрыть TELEGRAM_CHANNEL_ID из .env
  --thumb P.jpg    обложка для видео (jpeg, <200 КБ)
  --html           разрешить HTML-разметку в подписи (по умолчанию текст как есть)
  --silent         без звукового уведомления у подписчиков
  --yes            РЕАЛЬНО отправить. Без него инструмент только показывает, что ушло бы.

Нужны TELEGRAM_BOT_TOKEN и TELEGRAM_CHANNEL_ID в .env. ffprobe на PATH (размеры видео).
Bot API принимает файл не больше 50 МБ - более тяжёлые пересказы придётся жать.
"""
import json
import mimetypes
import os
import secrets
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://api.telegram.org/bot{token}/{method}"
MAX_UPLOAD = 50 * 1024 * 1024      # жёсткий потолок Bot API на отправку файла
MAX_CAPTION = 1024                 # лимит подписи к медиа
MAX_TEXT = 4096                    # лимит обычного сообщения
TIMEOUT = 600                      # заливка видео с домашнего канала бывает долгой


def load_env():
    env = {}
    p = os.path.join(ROOT, ".env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return {**env, **os.environ}


def get_arg(args, name, default=None):
    return args[args.index(name) + 1] if name in args else default


def multipart(fields, files):
    """Собрать multipart/form-data вручную: репозиторий stdlib-only, requests тут нет."""
    boundary = "----faceless" + secrets.token_hex(12)
    body = bytearray()
    for key, value in fields.items():
        if value is None:
            continue
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode()
        body += f"{value}\r\n".encode()
    for key, path in files.items():
        if not path:
            continue
        name = os.path.basename(path)
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        body += f"--{boundary}\r\n".encode()
        body += (f'Content-Disposition: form-data; name="{key}"; '
                 f'filename="{name}"\r\n').encode()
        body += f"Content-Type: {ctype}\r\n\r\n".encode()
        body += open(path, "rb").read() + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def call(token, method, fields=None, files=None):
    fields = fields or {}
    if files:
        data, ctype = multipart(fields, files)
    else:
        data = urllib.parse.urlencode({k: v for k, v in fields.items()
                                       if v is not None}).encode()
        ctype = "application/x-www-form-urlencoded"
    req = urllib.request.Request(API.format(token=token, method=method), data=data,
                                 headers={"Content-Type": ctype})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        try:
            detail = json.loads(detail).get("description", detail)
        except ValueError:
            pass
        sys.exit(f"Telegram отказал ({e.code}) на {method}: {detail}")
    except urllib.error.URLError as e:
        sys.exit(f"сеть недоступна: {e.reason}")


def probe(path):
    """Размеры и длительность - без них Telegram рисует видео квадратной заглушкой."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=width,height:format=duration", "-of", "json", path],
            capture_output=True, text=True, check=True).stdout
        info = json.loads(out)
        stream = (info.get("streams") or [{}])[0]
        return (stream.get("width"), stream.get("height"),
                int(float(info.get("format", {}).get("duration", 0))) or None)
    except Exception:
        return None, None, None


def human(n):
    return f"{n / 1024 / 1024:.1f} МБ"


def main():
    args = sys.argv[1:]
    env = load_env()
    token = env.get("TELEGRAM_BOT_TOKEN", "").strip()
    channel = (get_arg(args, "--channel") or env.get("TELEGRAM_CHANNEL_ID", "")).strip()

    if not token:
        sys.exit("нет TELEGRAM_BOT_TOKEN в .env — заведите бота у @BotFather,\n"
                 "сделайте его администратором канала и впишите токен в .env.")
    if not channel:
        sys.exit("нет TELEGRAM_CHANNEL_ID в .env (например @tsardumaet) "
                 "и не передан --channel.")

    if "--check" in args:
        me = call(token, "getMe").get("result", {})
        chat = call(token, "getChat", {"chat_id": channel}).get("result", {})
        print(f"бот:    @{me.get('username')} ({me.get('first_name')})")
        print(f"канал:  {chat.get('title')} ({channel}), тип {chat.get('type')}")
        admins = call(token, "getChatAdministrators", {"chat_id": channel}).get("result", [])
        ok = any(a.get("user", {}).get("id") == me.get("id") for a in admins)
        print("права:  " + ("бот администратор, публиковать может"
                            if ok else "бот НЕ администратор — постить не сможет"))
        return

    video = get_arg(args, "--video")
    photo = get_arg(args, "--photo")
    text = get_arg(args, "--text")
    caption_file = get_arg(args, "--caption-file")
    caption = get_arg(args, "--caption", "")
    if caption_file:
        caption = open(caption_file, encoding="utf-8").read().strip()

    if sum(bool(x) for x in (video, photo, text)) != 1:
        sys.exit("укажите ровно одно из: --video, --photo, --text.")

    media = video or photo
    if media and not os.path.exists(media):
        sys.exit(f"файл не найден: {media}")

    limit = MAX_TEXT if text else MAX_CAPTION
    body = text or caption
    if len(body) > limit:
        sys.exit(f"{'текст' if text else 'подпись'} длиной {len(body)} символов, "
                 f"Telegram принимает не больше {limit}.")

    fields = {"chat_id": channel}
    if "--html" in args:
        fields["parse_mode"] = "HTML"
    if "--silent" in args:
        fields["disable_notification"] = "true"

    if text:
        method, files = "sendMessage", {}
        fields["text"] = text
        summary = f"текст, {len(text)} символов"
    else:
        size = os.path.getsize(media)
        if size > MAX_UPLOAD:
            sys.exit(f"{media} весит {human(size)}, Bot API отдаёт не больше "
                     f"{human(MAX_UPLOAD)}. Сожмите файл или залейте его иначе.")
        if caption:
            fields["caption"] = caption
        if video:
            method = "sendVideo"
            files = {"video": video, "thumbnail": get_arg(args, "--thumb")}
            w, h, dur = probe(video)
            fields.update({"supports_streaming": "true", "width": w, "height": h,
                           "duration": dur})
            summary = (f"видео {os.path.basename(video)}, {human(size)}"
                       + (f", {w}x{h}, {dur} с" if w else "")
                       + (f", подпись {len(caption)} символов" if caption else ""))
        else:
            method, files = "sendPhoto", {"photo": photo}
            summary = f"фото {os.path.basename(photo)}, {human(size)}"

    print(f"канал:  {channel}")
    print(f"уйдёт:  {summary}")
    if "--yes" not in args:
        print("\nсухой прогон: ничего не отправлено. Добавьте --yes, чтобы опубликовать.")
        return

    res = call(token, method, fields, files).get("result", {})
    chat = res.get("chat", {})
    mid = res.get("message_id")
    if chat.get("username") and mid:
        print(f"опубликовано: https://t.me/{chat['username']}/{mid}")
    else:
        print(f"опубликовано, message_id {mid}")


if __name__ == "__main__":
    main()
