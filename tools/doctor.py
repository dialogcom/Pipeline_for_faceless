#!/usr/bin/env python3
"""
doctor.py — что это окружение МОЖЕТ, а чего не может, до того как вы начали работу.

Существует потому, что разница между рабочей копией на машине автора и контейнером,
поднятым из GitHub, велика и не видна: `.env` в git не хранится, `*/output/` и `*/voice/`
тоже, а часть платных кадров в `media/projects/` оказалась не закоммичена. Сессия из
GitHub это выясняет по ходу дела - обычно после того, как что-то уже написано в расчёте
на работающую генерацию.

Печатает только ИМЕНА ключей, никогда значения.

    python3 tools/doctor.py            # отчёт
    python3 tools/doctor.py --brief    # одна строка на трек
"""
import os
import shutil
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OK, NO, WARN = "  ok  ", "  НЕТ ", "  ~   "


# Ровно те имена, которые что-то значат для этого репозитория. Сканировать os.environ по
# суффиксам (_KEY, _TOKEN, _ID) нельзя: в контейнере полно служебных переменных с такими
# окончаниями, и набор ключей получается непустым там, где ключей нет ни одного.
KNOWN_KEYS = ("INWORLD_API_KEY", "ELEVENLABS_API_KEY", "FAL_KEY", "CLOUDFLARE_API_TOKEN",
              "CLOUDFLARE_ACCOUNT_ID", "OPENROUTER_API_KEY", "GEMINI_API_KEY",
              "MODELSCOPE_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHANNEL_ID")


def load_env_names():
    """Имена заполненных ключей. Значения не читаются дальше проверки на пустоту."""
    names = set()
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if v.strip().strip('"').strip("'"):
                    names.add(k.strip())
    for k in KNOWN_KEYS:
        if os.environ.get(k, "").strip():
            names.add(k)
    return names


def have(cmd):
    # ~/bin тоже: сессионный хук кладёт туда статический ffmpeg, когда apt недоступен, и
    # экспортирует PATH через CLAUDE_ENV_FILE - но отдельный дочерний шелл его может не иметь,
    # и отчёт врал бы про отсутствие того, что на самом деле стоит.
    return shutil.which(cmd) is not None or (Path.home() / "bin" / cmd).is_file()


def python_pkg(name):
    try:
        __import__(name)
        return True
    except Exception:
        return False


# Ключа мало: у окружения есть своя сетевая политика, и удалённый контейнер может не
# пускать к API вообще. Выяснять это ПОСЛЕ того, как ключи вставлены и текст написан, -
# ровно тот способ, которым это выяснилось в первый раз.
ENDPOINTS = [
    ("Inworld (озвучка)", "https://api.inworld.ai/", "INWORLD_API_KEY"),
    ("Cloudflare Workers AI (кадры)", "https://api.cloudflare.com/", "CLOUDFLARE_API_TOKEN"),
    ("OpenRouter (кадры)", "https://openrouter.ai/", "OPENROUTER_API_KEY"),
    ("fal.ai (видео)", "https://fal.run/", "FAL_KEY"),
    ("ElevenLabs (голос, SFX)", "https://api.elevenlabs.io/", "ELEVENLABS_API_KEY"),
]


def reachable(url, timeout=6):
    """Дошли ли мы до самого хоста. Любой HTTP-ответ, включая 401/404, - это успех:
    значит соединение установлено и упирается только в авторизацию. Отказ шлюза на CONNECT
    или таймаут - нет."""
    try:
        urllib.request.urlopen(urllib.request.Request(url, method="GET"), timeout=timeout)
        return True, ""
    except urllib.error.HTTPError:
        return True, ""
    except urllib.error.URLError as e:
        r = str(e.reason)
        if "403" in r and "Tunnel" in r:
            return False, "запрещено прокси окружения"
        return False, r[:60]
    except (socket.timeout, OSError) as e:
        return False, str(e)[:60]


TRACKS = [
    ("write-in-voice / audit-voice", [], [], "профили голоса и аудит текста"),
    ("make-retelling", ["INWORLD_API_KEY"], ["pil", "ffmpeg"], "длинные пересказы, retellings/"),
    ("make-narrated-short", ["INWORLD_API_KEY"], ["pil", "ffmpeg"], "60-секундные эпизоды"),
    ("make-vox", ["INWORLD_API_KEY"], ["node", "remotion"], "коллажные шорты"),
    ("make-short", ["ELEVENLABS_API_KEY"], ["node", "remotion"], "TSX-шорты"),
    ("make-ai-short", ["FAL_KEY"], ["node", "remotion"], "генеративное видео"),
    ("repurpose-recording", [], ["ffmpeg"], "нарезка своих записей"),
]
IMAGE_KEYS = [("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"), ("OPENROUTER_API_KEY",),
              ("GEMINI_API_KEY",), ("FAL_KEY",), ("MODELSCOPE_API_KEY",)]
NEEDS_IMAGES = {"make-retelling", "make-narrated-short", "make-vox"}


def main():
    brief = "--brief" in sys.argv
    keys = load_env_names()
    tools = {
        "pil": python_pkg("PIL"),
        "ffmpeg": have("ffmpeg"),
        "ffprobe": have("ffprobe"),
        "node": have("node") or have("npx"),
        "remotion": (ROOT / "remotion/node_modules").is_dir(),
    }
    image_route = next((r[0] for r in IMAGE_KEYS if all(k in keys for k in r)), None)
    remote = os.environ.get("CLAUDE_CODE_REMOTE") == "true"

    print("=" * 66)
    print(f"  ОКРУЖЕНИЕ: {'контейнер из GitHub' if remote else 'локальная машина'}"
          f"   ({ROOT.name})")
    print("=" * 66)

    print("\nКЛЮЧИ (.env" + (" отсутствует" if not (ROOT / '.env').exists() else "") + ")")
    for group in KNOWN_KEYS:
        print(f"{OK if group in keys else NO} {group}")
    print(f"  маршрут для картинок: {image_route or 'НЕТ НИ ОДНОГО'}")

    print("\nИНСТРУМЕНТЫ")
    for name, present in tools.items():
        print(f"{OK if present else NO} {name}")
    print(f"  python {sys.version.split()[0]}")

    # Платные кадры должны быть в гите. Пустой каталог = эпизод нельзя пересобрать даром.
    print("\nМЕДИА (платные пиксели, которые по правилу репозитория хранятся в гите)")
    projects = sorted((ROOT / "media/projects").glob("*")) if (ROOT / "media/projects").is_dir() else []
    empty = []
    for proj in projects:
        imgs = proj / "images"
        if imgs.is_dir():
            # .jpg тоже кадр: с 25.08.2026 кадры хранятся в JPEG, а не PNG
            count = lambda d: len(list(d.glob("*.png"))) + len(list(d.glob("*.jpg")))
            n = count(imgs)
            alt = sum(count(d) for d in proj.glob("images-*"))
            if n == 0:
                empty.append((proj.name, alt))
    if empty:
        for name, alt in empty:
            extra = f", но {alt} шт. лежит в images-*/" if alt else ""
            print(f"{WARN} media/projects/{name}/images пуст{extra}")
        print("       -> эпизоды этих серий нельзя пересобрать без повторной оплаты кадров")
    else:
        print(f"{OK} все каталоги images непусты ({len(projects)} проектов)")

    print("\nСЕТЬ (доступны ли API из этого окружения)")
    blocked_hosts = set()
    for label, url, key in ENDPOINTS:
        ok, why = reachable(url)
        if not ok:
            blocked_hosts.add(key)
        mark = OK if ok else NO
        print(f"{mark} {label:<32}{'' if ok else why}")

    print("\nЧТО ЗАПУСТИТСЯ ЗДЕСЬ")
    blocked_any = False
    for name, need_keys, need_tools, desc in TRACKS:
        missing = [k for k in need_keys if k not in keys]
        missing += [f"сеть до {k.split('_')[0].lower()}" for k in need_keys if k in blocked_hosts]
        missing += [t for t in need_tools if not tools.get(t)]
        if name in NEEDS_IMAGES:
            if not image_route:
                missing.append("ключ для картинок")
            elif image_route in blocked_hosts:
                missing.append("сеть до провайдера картинок")
        if missing:
            blocked_any = True
            print(f"{NO} {name:<28} нет: {', '.join(missing)}")
        else:
            print(f"{OK} {name:<28} {desc}")

    if blocked_any:
        print("\nЧТО С ЭТИМ ДЕЛАТЬ")
        if not keys:
            print("  bash tools/find_keys.sh    найти .env от прошлых проектов (значения не печатает)")
            print("  bash tools/setup_keys.sh   вписать ключи, ввод не отображается")
            print("  либо Secrets репозитория + вкладка Actions -> «Собрать пересказ»")
        if blocked_hosts:
            print("  сеть закрыта политикой окружения — ключи тут не помогут. Варианты:")
            print("    * собрать локально (Claude Code на своей машине)")
            print("    * вкладка Actions -> «Собрать пересказ» (у раннеров GitHub сеть открыта)")
            print("    * поменять сетевую политику окружения на claude.ai/code")
        if not tools["remotion"]:
            print("  cd remotion && npm install --no-audit --no-fund   для TSX-треков")
        print("  подробности и три места, где могут жить ключи: retellings/DESIGN.md")
    print()


if __name__ == "__main__":
    main()
