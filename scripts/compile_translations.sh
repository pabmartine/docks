#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

for lang in en es; do
    po_file="$ROOT_DIR/locale/$lang/LC_MESSAGES/docks.po"
    mo_file="$ROOT_DIR/locale/$lang/LC_MESSAGES/docks.mo"
    if [[ -f "$po_file" ]]; then
        msgfmt "$po_file" -o "$mo_file"
        echo "Compiled $mo_file"
    fi
done
