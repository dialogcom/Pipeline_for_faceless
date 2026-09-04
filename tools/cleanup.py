#!/usr/bin/env python3
"""
cleanup.py — освободить диск, не тронув ничего невосстановимого.

Проект растёт быстрее, чем кажется: один пятиминутный пересказ оставляет после себя
около 800 МБ, из которых 620 МБ — черновики ffmpeg, нужные ровно до конца сборки.
Убирать это руками опасно ровно потому, что рядом лежат вещи, которых больше нигде нет:
исходные записи автора и оплаченные кадры.

Поэтому решение здесь принимает не память человека, а два правила:

1. **Удаляем только то, что git игнорирует.** Всё отслеживаемое неприкосновенно —
   оплаченные кадры и слои лежат в git по правилу репозитория, и если файл там, значит
   его сознательно решили хранить.
2. **Плюс явный список защищённых путей** для того, что git игнорирует, но
   восстановить нельзя: raw-footage/ (исходники автора) и кэш TTS (оплачен у Inworld).

Всё, что не проходит оба фильтра, не удаляется — даже если очень большое.

Отдельно проверяется вот что: рендер воспроизводим только если жив материал, из
которого он собран. Если у vox-ролика удалили слои, его mp4 в remotion/out — последняя
копия, и скрипт её не тронет, а предупредит.

Готовые ролики по умолчанию НЕ трогаются. Это выучено дорого: 22 августа рендер был
удалён сразу после того, как Metricool сказал «опубликовано», — а публикация оказалась
неполной (YouTube отклонил обложку), ролик пришлось снимать с канала, и локальной копии
уже не было. «Опубликовано» и «опубликовано правильно» — разные события; второе
подтверждает человек, а не API.

Использование:
  python tools/cleanup.py              # показать, что удалилось бы (черновики)
  python tools/cleanup.py --yes        # снести черновики
  python tools/cleanup.py --outputs --yes   # ВДОБАВОК снести готовые ролики
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Пути, которые не удаляются никогда, даже будучи в gitignore. Всё это либо принадлежит
# автору и нигде больше не существует, либо стоило денег.
PROTECTED = [
    "raw-footage",        # исходные записи под repurpose-recording
    "media/projects",     # оплаченные кадры и слои (они и так в git, но пусть будет вдвойне)
    ".git",
    ".env",
]

# Черновики: живут ровно до конца сборки, воссоздаются за минуты из кэша озвучки и кадров.
SCRATCH_GLOBS = [
    "*/*/voice/*_build",          # ffmpeg-черновик пересказов и narrated-shorts
    "remotion/out/qa",            # кадры QA
]

# Готовые ролики. Воспроизводимы, но дороже по времени — отдельный флаг.
OUTPUT_GLOBS = [
    "*/*/output",
    "remotion/out",
]

JUNK_NAMES = [".DS_Store", "Thumbs.db"]


def sh(*args):
    return subprocess.run(args, capture_output=True, text=True, cwd=ROOT)


def is_ignored(path):
    """git игнорирует этот путь? Только такие вообще рассматриваются к удалению."""
    return sh("git", "check-ignore", "-q", str(path)).returncode == 0


def is_tracked(path):
    """Внутри пути есть хоть один отслеживаемый файл? Тогда путь неприкосновенен."""
    r = sh("git", "ls-files", "--error-unmatch", str(path))
    if r.returncode == 0:
        return True
    return bool(sh("git", "ls-files", str(path)).stdout.strip())


def protected(path):
    rel = str(path.relative_to(ROOT))
    return any(rel == p or rel.startswith(p + "/") for p in PROTECTED)


def size_kb(path):
    r = sh("du", "-sk", str(path))
    try:
        return int(r.stdout.split()[0])
    except (ValueError, IndexError):
        return 0


def vox_layers_missing(mp4):
    """Рендер vox-N воспроизводим только пока жив каталог его слоёв. Если слои удалили,
    этот mp4 — последняя копия, и трогать его нельзя. Имя композиции в remotion/out
    (Vox17PetlyaISpiral) сопоставляется с каталогом media/projects/vox-17-... по номеру."""
    name = mp4.stem
    if not name.lower().startswith("vox"):
        return False
    digits = ""
    for ch in name[3:]:
        if ch.isdigit():
            digits += ch
        else:
            break
    if not digits:
        return False
    hits = list((ROOT / "media/projects").glob(f"vox-{int(digits)}-*/layers"))
    return not any(h.is_dir() and any(h.iterdir()) for h in hits)


def collect(globs):
    out = []
    for g in globs:
        for p in ROOT.glob(g):
            if protected(p) or not is_ignored(p) or is_tracked(p):
                continue
            out.append(p)
    return out


def main():
    args = sys.argv[1:]
    do_it = "--yes" in args
    with_outputs = "--outputs" in args

    targets, skipped = [], []

    for p in collect(SCRATCH_GLOBS):
        targets.append((p, "черновик сборки"))

    if with_outputs:
        for p in collect(OUTPUT_GLOBS):
            if p.is_dir():
                for f in sorted(p.glob("*.mp4")):
                    if vox_layers_missing(f):
                        skipped.append((f, "слои удалены — рендер невоспроизводим"))
                    else:
                        targets.append((f, "готовый ролик"))
            elif p.suffix == ".mp4":
                targets.append((p, "готовый ролик"))

    junk = [p for name in JUNK_NAMES for p in ROOT.rglob(name)
            if ".git/" not in str(p)]

    total = 0
    print(f"{'':>9}  что")
    for p, why in sorted(targets, key=lambda t: -size_kb(t[0])):
        kb = size_kb(p)
        total += kb
        print(f"{kb // 1024:>7} МБ  {p.relative_to(ROOT)}  [{why}]")
    if junk:
        print(f"{len(junk):>7} шт  мусор macOS/Windows")

    print(f"\n  освободится: {total // 1024} МБ")

    if skipped:
        print("\n  НЕ ТРОГАЮ:")
        for p, why in skipped:
            print(f"{size_kb(p) // 1024:>7} МБ  {p.relative_to(ROOT)}  <- {why}")

    if not with_outputs:
        print("\n  готовые ролики не тронуты (нужен --outputs). Сносить их стоит только\n"
              "  после того, как публикация проверена ГЛАЗАМИ, а не по статусу API.")
    if not do_it:
        print("\n(ничего не удалено — это просмотр. Повторите с --yes)")
        return

    import shutil
    for p, _ in targets:
        shutil.rmtree(p) if p.is_dir() else p.unlink(missing_ok=True)
    for p in junk:
        p.unlink(missing_ok=True)
    print(f"\nудалено, освобождено {total // 1024} МБ")


if __name__ == "__main__":
    main()
