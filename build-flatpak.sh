#!/bin/bash
set -e

echo "Building Yafti GTK Flatpak..."

# Install flatpak-builder if not present
if ! command -v flatpak-builder &> /dev/null; then
    echo "Installing flatpak-builder..."
    sudo pacman -S flatpak-builder --noconfirm
fi

# Add Flathub repo if not present
if ! flatpak remote-list | grep -q flathub; then
    echo "Adding Flathub repository..."
    flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
fi

# Install runtime and SDK
echo "Installing GNOME runtime and SDK..."
flatpak install -y --user flathub org.gnome.Platform//48 org.gnome.Sdk//48 2>/dev/null || true

# Build the flatpak
echo "Building flatpak package..."
flatpak-builder --user --install --force-clean build-dir com.github.yafti.gtk.yml

echo ""
echo "✓ Build complete!"
echo ""
echo "To run the app:"
echo "  flatpak run com.github.yafti.gtk"
echo ""
echo "To export as a single-file bundle:"
echo "  flatpak build-bundle ~/.local/share/flatpak/repo yafti-gtk.flatpak com.github.yafti.gtk"
