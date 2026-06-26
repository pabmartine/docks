#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
POT_FILE="$ROOT_DIR/locale/docks.pot"

mkdir -p "$ROOT_DIR/locale"

xgettext \
    --language=Python \
    --keyword=_ \
    --from-code=UTF-8 \
    --output="$POT_FILE" \
    "$ROOT_DIR/src/docks/app.py" \
    "$ROOT_DIR/src/docks/ui/window.py" \
    "$ROOT_DIR/src/docks/services/docker_service.py"

for lang in en es; do
    po_dir="$ROOT_DIR/locale/$lang/LC_MESSAGES"
    po_file="$po_dir/docks.po"
    mkdir -p "$po_dir"

    if [[ -f "$po_file" ]]; then
        msgmerge --backup=none --update "$po_file" "$POT_FILE"
        echo "Updated $po_file"
    else
        msginit \
            --no-translator \
            --input="$POT_FILE" \
            --output-file="$po_file" \
            --locale="$lang"
        echo "Created $po_file"
    fi
done

echo "Generated $POT_FILE"
