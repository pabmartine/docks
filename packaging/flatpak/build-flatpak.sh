#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP_ID="com.pabmartine.Docks"
BUILD_DIR="$ROOT_DIR/build-dir"
REPO_DIR="$ROOT_DIR/repo"
MANIFEST="$ROOT_DIR/packaging/flatpak/com.pabmartine.Docks.yaml"

echo "Preparando construccion de Flatpak..."

rm -rf "$BUILD_DIR" "$REPO_DIR"

echo "Verificando runtimes de Flatpak..."
if ! flatpak list --runtime | grep -q "org.gnome.Platform.*50"; then
    echo "Instalando runtime de GNOME Platform 50..."
    flatpak install --user flathub org.gnome.Platform//50 org.gnome.Sdk//50 -y
fi

echo "Actualizando catalogos y compilando traducciones..."
bash "$ROOT_DIR/scripts/extract_strings.sh"
bash "$ROOT_DIR/scripts/compile_translations.sh"

echo "Construyendo Flatpak..."
flatpak-builder --user --install --force-clean "$BUILD_DIR" "$MANIFEST"

echo "Creando repositorio local..."
flatpak-builder --user --repo="$REPO_DIR" --force-clean "$BUILD_DIR" "$MANIFEST"

echo "Creando bundle..."
flatpak build-bundle "$REPO_DIR" "$ROOT_DIR/$APP_ID.flatpak" "$APP_ID"

echo "Flatpak construido exitosamente."
echo
echo "Bundle generado:"
echo "  $ROOT_DIR/$APP_ID.flatpak"
echo
echo "Comandos utiles:"
echo "  Instalar el bundle:"
echo "    flatpak install --user \"$ROOT_DIR/$APP_ID.flatpak\""
echo
echo "  Ejecutar la app instalada:"
echo "    flatpak run $APP_ID"
echo
echo "  Ejecutar directamente desde el repositorio local generado:"
echo "    flatpak run --user --sideload-repo=\"$REPO_DIR\" $APP_ID"
