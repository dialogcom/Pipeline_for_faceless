#!/usr/bin/env python3
"""
publish_queue.py — очередь отложенных публикаций в Telegram.

Смысл: не помнить каждый день про очередной эпизод. Очередь описывает, что и
когда уходит, а launchd (или запуск руками) раз в сутки отправляет ОДИН
созревший пост. Один запуск - максимум одна публикация: если Мак был выключен
три дня, серия не вывалится в канал пачкой.

Формат очереди (JSON-список, порядок = порядок публикации):
  [
    {"video": "narrated-shorts/x/output/ep-04.mp4",
     "caption": "narrated-shorts/x/captions/caption-04.txt",
     "publish_at": "2026-08-31 10:00"}
  ]
Поле "posted_at" инструмент дописывает сам после успешной отправки. Записи с
ним больше не трогаются - повторно тот же ролик не уйдёт.

Usage:
  python tools/publish_queue.py --status                 что в очереди
  python tools/publish_queue.py                          сухой прогон созревшего
  python tools/publish_queue.py --yes                    отправить созревшее
  python tools/publish_queue.py --queue путь.json --yes
  python tools/publish_queue.py --media-root media --yes    (так запускается CI)

По умолчанию очередь - publish-queue.json в корне репозитория. Ролики ищутся по
пути из записи; если его нет (в клоне репозитория output/ отсутствует - он в
.gitignore), берётся файл с тем же именем из --media-root. Так одна и та же
очередь работает и на Маке, и на раннере GitHub, где видео лежат в ассетах релиза.
"""
import json
import os
import subprocess
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_QUEUE = os.path.join(ROOT, "publish-queue.json")
POSTER = os.path.join(ROOT, "tools", "post_telegram.py")
TIME_FORMATS = ("%Y-%m-%d %H:%M", "%Y-%m-%d")


def get_arg(args, name, default=None):
    return args[args.index(name) + 1] if name in args else default


def parse_time(value):
    for fmt in TIME_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    sys.exit(f"не разобрать дату {value!r}: ждём «ГГГГ-ММ-ДД» или «ГГГГ-ММ-ДД ЧЧ:ММ»")


def load(path):
    if not os.path.exists(path):
        sys.exit(f"очереди нет: {path}")
    with open(path, encoding="utf-8") as f:
        items = json.load(f)
    if not isinstance(items, list):
        sys.exit("очередь должна быть списком записей")
    return items


def save(path, items):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
        f.write("\n")


def resolve(rel_path, media_root=None):
    """Путь к ролику: сначала как в очереди, потом по имени файла в media_root."""
    direct = os.path.join(ROOT, rel_path)
    if os.path.exists(direct):
        return direct
    if media_root:
        fallback = os.path.join(media_root, os.path.basename(rel_path))
        if os.path.exists(fallback):
            return fallback
    sys.exit(f"ролик из очереди не найден: {rel_path}"
             + (f" (и нет {os.path.basename(rel_path)} в {media_root})" if media_root else ""))


def log(message):
    print(f"{datetime.now():%Y-%m-%d %H:%M}  {message}", flush=True)


def main():
    args = sys.argv[1:]
    path = get_arg(args, "--queue", DEFAULT_QUEUE)
    items = load(path)
    now = datetime.now()

    if "--status" in args:
        for i, item in enumerate(items, 1):
            when = item.get("publish_at", "?")
            if item.get("posted_at"):
                state = f"отправлено {item['posted_at']}"
            elif parse_time(when) <= now:
                state = "СОЗРЕЛО"
            else:
                state = "ждёт"
            print(f"{i}. {when}  {state}\n   {item.get('video', '?')}")
        return

    due = next((x for x in items
                if not x.get("posted_at") and parse_time(x["publish_at"]) <= now), None)
    if due is None:
        pending = [x for x in items if not x.get("posted_at")]
        log(f"отправлять нечего (в очереди ждёт: {len(pending)})")
        return

    video = resolve(due["video"], get_arg(args, "--media-root"))
    caption = os.path.join(ROOT, due["caption"]) if due.get("caption") else None
    if caption and not os.path.exists(caption):
        sys.exit(f"подпись из очереди не найдена: {caption}")

    cmd = [sys.executable, POSTER, "--video", video]
    if caption:
        cmd += ["--caption-file", caption]
    if "--yes" in args:
        cmd.append("--yes")

    log(f"публикую {due['video']}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    sys.stdout.write(result.stdout)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        # Отметку не ставим: следующий запуск попробует снова.
        sys.exit(f"отправка не удалась, код {result.returncode}")

    if "--yes" not in args:
        log("сухой прогон: отметка в очереди не поставлена")
        return

    due["posted_at"] = f"{now:%Y-%m-%d %H:%M}"
    for line in result.stdout.splitlines():
        if line.startswith("опубликовано:"):
            due["url"] = line.split(":", 1)[1].strip()
    save(path, items)
    log(f"готово, осталось в очереди: {sum(1 for x in items if not x.get('posted_at'))}")


if __name__ == "__main__":
    main()
