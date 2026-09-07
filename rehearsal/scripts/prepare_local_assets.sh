#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -n "${AVATAR_MODEL_SOURCE:-}" ]]; then
  test -f "$AVATAR_MODEL_SOURCE" || { echo "Файл AVATAR_MODEL_SOURCE не найден" >&2; exit 1; }
  mkdir -p frontend/public/models
  cp "$AVATAR_MODEL_SOURCE" frontend/public/models/avatar.glb
  echo "Аватар подготовлен: frontend/public/models/avatar.glb"
fi

if [[ -n "${WHISPER_MODEL_SOURCE:-}" ]]; then
  test -d "$WHISPER_MODEL_SOURCE" || { echo "Папка WHISPER_MODEL_SOURCE не найдена" >&2; exit 1; }
  mkdir -p models
  test ! -e models/whisper-small || { echo "models/whisper-small уже существует. Укажите его путь в WHISPER_MODEL или выберите другую папку вручную." >&2; exit 1; }
  cp -R "$WHISPER_MODEL_SOURCE" models/whisper-small
  echo "Whisper подготовлен: models/whisper-small"
fi

if [[ -z "${AVATAR_MODEL_SOURCE:-}${WHISPER_MODEL_SOURCE:-}" ]]; then
  echo "Укажите AVATAR_MODEL_SOURCE и/или WHISPER_MODEL_SOURCE. Пример есть в README." >&2
  exit 2
fi
