#!/usr/bin/env bash
# find_keys.sh — найти .env от прошлых проектов и показать, КАКИЕ ключи в них заполнены.
#
#   bash tools/find_keys.sh            # искать в домашней папке
#   bash tools/find_keys.sh ~/Projects # искать в конкретной папке
#
# Печатаются только пути и имена ключей. Значения не выводятся никогда - иначе они
# оказались бы в скроллбеке, в скриншоте или в переписке.
set -uo pipefail

ROOT="${1:-$HOME}"
WANT="INWORLD_API_KEY|CLOUDFLARE_API_TOKEN|CLOUDFLARE_ACCOUNT_ID|ELEVENLABS_API_KEY|FAL_KEY|OPENROUTER_API_KEY|GEMINI_API_KEY|MODELSCOPE_API_KEY"

echo "ищу файлы .env в $ROOT (это может занять минуту)..."
echo

found=0
while IFS= read -r f; do
  keys=$(grep -oE "^[[:space:]]*(${WANT})=.+" "$f" 2>/dev/null | cut -d= -f1 | tr -d ' ' | sort -u)
  [ -z "$keys" ] && continue
  found=$((found+1))
  echo "$f"
  echo "$keys" | sed 's/^/    /'
  echo "    изменён: $(date -r "$f" '+%Y-%m-%d %H:%M' 2>/dev/null || echo '?')"
  echo
done < <(find "$ROOT" -type f -name ".env" \
           -not -path "*/node_modules/*" -not -path "*/.Trash/*" \
           -not -path "*/Library/Caches/*" 2>/dev/null)

if [ "$found" -eq 0 ]; then
  echo "не нашлось ни одного .env с заполненными ключами."
  echo "проверьте вручную: менеджер паролей, заметки, письма от Inworld и Cloudflare,"
  echo "или просто выпустите новые - это бесплатно и занимает пару минут."
else
  echo "найдено файлов: $found"
  echo
  echo "перенести ключи в текущий проект, не показывая их на экране:"
  echo "    bash tools/setup_keys.sh"
  echo "посмотреть значение одного ключа, чтобы скопировать:"
  echo "    grep INWORLD_API_KEY <путь-из-списка-выше>"
fi
