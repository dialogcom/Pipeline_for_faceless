#!/usr/bin/env bash
# setup_keys.sh — записать API-ключи в .env, не показывая их на экране и не оставляя
# в истории команд.
#
#   bash tools/setup_keys.sh                 # спросит все ключи трека retellings
#   bash tools/setup_keys.sh INWORLD_API_KEY # спросит только один
#
# Почему не просто `echo KEY=... >> .env`: такая строка целиком попадает в ~/.bash_history
# и в вывод терминала, откуда её видно любому, кто заглянет через плечо или в скроллбек.
# `read -rs` не отображает ввод, а значение живёт только в переменной оболочки, которая
# стирается в конце. Существующая строка обновляется на месте, а не дублируется.
set -euo pipefail

cd "$(dirname "$0")/.."
ENV_FILE=".env"

DEFAULT_KEYS=(INWORLD_API_KEY CLOUDFLARE_API_TOKEN CLOUDFLARE_ACCOUNT_ID)
KEYS=("$@")
[ ${#KEYS[@]} -eq 0 ] && KEYS=("${DEFAULT_KEYS[@]}")

if [ ! -f "$ENV_FILE" ]; then
  [ -f .env.example ] && cp .env.example "$ENV_FILE" || : > "$ENV_FILE"
  echo "создан $ENV_FILE из шаблона"
fi
chmod 600 "$ENV_FILE"

if ! grep -qxF ".env" .gitignore 2>/dev/null; then
  echo "ОСТАНОВЛЕНО: .env не указан в .gitignore — ключи утекли бы в репозиторий." >&2
  exit 1
fi

for KEY in "${KEYS[@]}"; do
  printf '%s (ввод не отображается, Enter — пропустить): ' "$KEY"
  # Читаем с терминала, а не со stdin: так значение нельзя случайно передать по пайпу
  # из файла или из истории. Без терминала (CI, тест) падаем обратно на stdin.
  if [ -r /dev/tty ] && [ -t 1 ]; then
    IFS= read -rs VALUE < /dev/tty || VALUE=""
  else
    IFS= read -r VALUE || VALUE=""
  fi
  echo
  if [ -z "$VALUE" ]; then
    echo "  пропущен"
    continue
  fi
  TMP="$(mktemp)"
  grep -v -E "^[[:space:]]*${KEY}=" "$ENV_FILE" > "$TMP" || true
  printf '%s=%s\n' "$KEY" "$VALUE" >> "$TMP"
  mv "$TMP" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  unset VALUE
  echo "  записан (${#KEY} символов имени, значение не выводится)"
done

echo
echo "в $ENV_FILE сейчас заполнены:"
grep -E '^[A-Z_]+=.+' "$ENV_FILE" | cut -d= -f1 | sed 's/^/  /'
echo
echo "проверка конвейера:"
python3 tools/build_retelling.py --spec retellings/petlya-i-spiral/script.json --dry-run 2>&1 | tail -4 || true
