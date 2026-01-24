#!/bin/bash
set -euo pipefail

echo "Building Yafti GTK Flatpak..."

if ! command -v flatpak >/dev/null 2>&1; then
    echo "Error: 'flatpak' not found. Install Flatpak to build locally." >&2
    exit 1
fi

mkdir -p repo build-dir

echo "Running flatpak-builder..."
flatpak run org.flatpak.Builder --disable-rofiles-fuse --user --force-clean build-dir com.github.yafti.gtk.yml --repo=repo

echo "Exporting bundle..."
flatpak build-bundle repo yafti-gtk.flatpak io.github.xxjsonderuloxx.yafti-gtk

printf "\n✓ Build complete — yafti-gtk.flatpak created in repo root.\n"
echo "To install locally:  flatpak install --user -y yafti-gtk.flatpak"
