#!/usr/bin/env python3
"""
add_peel_to_episodes.py — Добавить эффект page-peel с афоризмом Шри Чинмоя
к каждому эпизоду серии «Последний вулкан».

Использует tools/page_peel.py для создания эффекта отворота страницы
в конце каждого видео. Под отогнутым краем появляется афоризм.

Usage:
  python tools/add_peel_to_episodes.py              # preview (previews only)
  python tools/add_peel_to_episodes.py --build      # build all 5 with peel
  python tools/add_peel_to_episodes.py --upload     # build + upload to YouTube
  python tools/add_peel_to_episodes.py --ep 1       # process episode 1 only
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERIES = "posledniy-vulkan-shorts"
SERIES_DIR = os.path.join(ROOT, "narrated-shorts", SERIES)
OUTPUT_DIR = os.path.join(SERIES_DIR, "output")
PEEL_DIR = os.path.join(SERIES_DIR, "peel")
PEEL_SCRIPT = os.path.join(ROOT, "tools", "page_peel.py")

# Афоризмы для каждого эпизода (текст + разбивка на строки)
EPISODES = [
    {
        "slug": "pochtalon-kotoryy-doshel",
        "title": "Почтальон, который дошёл",
        "peel_text": "Счастье — это вечное\nпутешествие нашего сердца,\nа не отдалённая цель.",
    },
    {
        "slug": "chislo-na-kotorom-derzhalos-imya",
        "title": "Число, на котором держалось имя",
        "peel_text": "Решимость может\nизменить ваш ум.\nРешимость может\nизменить ваше сердце.\nРешимость может\nрешительно изменить\nвсю вашу жизнь.",
    },
    {
        "slug": "pravilo-bylo-pod-rukoy-trizhdy",
        "title": "Правило было под рукой — трижды",
        "peel_text": "Не сдавайся!\nОдна лишь вера помогает нам\nвыжить и вдохновляет\nсмотреть вперёд.",
    },
    {
        "slug": "iskusitel-prihodit-na-sorokovoy",
        "title": "Искуситель приходит на сороковой",
        "peel_text": "Ты не счастлив\nи никогда не будешь счастливым,\nпотому что ты не настолько\nпотерял себя,\nчтобы себя найти.",
    },
    {
        "slug": "chto-stoilo-eto-chislo",
        "title": "Что стоило это число?",
        "peel_text": "Нужно понять,\nчто внутренняя сила\nбесконечно сильнее\nсобытий внешней жизни.",
    },
]

AUTHOR = "Шри Чинмой"


def find_video(slug):
    """Find the existing MP4 for this episode."""
    for f in os.listdir(OUTPUT_DIR):
        if f.startswith("short-") and slug in f and f.endswith(".mp4"):
            return os.path.join(OUTPUT_DIR, f)
    return None


def main():
    args = sys.argv[1:]
    preview_only = "--preview" in args or not any(a in args for a in ("--build", "--upload"))
    build = "--build" in args or "--upload" in args
    upload = "--upload" in args
    single_ep = None
    if "--ep" in args:
        single_ep = int(args[args.index("--ep") + 1]) - 1

    os.makedirs(PEEL_DIR, exist_ok=True)

    for i, ep in enumerate(EPISODES):
        if single_ep is not None and i != single_ep:
            continue

        video = find_video(ep["slug"])
        if not video:
            print(f"  ✗ Видео не найдено: {ep['slug']}", file=sys.stderr)
            continue

        out_path = os.path.join(PEEL_DIR, f"short-{i+1:02d}-{ep['slug']}-peel.mp4")
        preview_path = os.path.join(PEEL_DIR, f"short-{i+1:02d}-{ep['slug']}-preview.png")

        print(f"\n=== Эпизод {i+1}: {ep['title']} ===", file=sys.stderr)

        # Build command
        # Force system python3 which has Pillow installed
        py = "/usr/bin/python3"
        cmd = [
            py, PEEL_SCRIPT,
            "--video", video,
            "--text", ep["peel_text"],
            "--author", AUTHOR,
            "--peel", "1.8",
            "--hold", "3.5",
        ]

        if preview_only:
            cmd += ["--preview", preview_path]
            print(f"  Превью: {preview_path}", file=sys.stderr)
        else:
            cmd += ["--out", out_path]
            print(f"  Выход: {out_path}", file=sys.stderr)

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  ОШИБКА: {result.stderr}", file=sys.stderr)
            continue
        print(f"  {result.stdout.strip()}", file=sys.stderr)

        if upload:
            print(f"  Загрузка на YouTube...", file=sys.stderr)
            upload_cmd = [
                py, os.path.join(ROOT, "tools", "upload_youtube.py"),
                "--upload", str(i + 1),
            ]
            ur = subprocess.run(upload_cmd, capture_output=True, text=True)
            print(f"  {ur.stdout.strip()}", file=sys.stderr)
            if ur.returncode != 0:
                print(f"  ОШИБКА загрузки: {ur.stderr}", file=sys.stderr)

    print("\n✅ Готово", file=sys.stderr)


if __name__ == "__main__":
    main()
