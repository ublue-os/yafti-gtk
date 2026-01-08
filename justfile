_default:
    @just --list

# Build the flatpak using flatpak-builder from Flathub
build:
    ./build-flatpak.sh
    @test -f yafti-gtk.flatpak && echo "✓ Flatpak built successfully" || (echo "✗ Build failed - flatpak not found" && exit 1)

# Install the built flatpak
install:
    @test -f yafti-gtk.flatpak || (echo "✗ yafti-gtk.flatpak not found - run 'just build' first" && exit 1)
    flatpak install --user -y yafti-gtk.flatpak

# Uninstall the flatpak
uninstall:
    flatpak uninstall --user -y com.github.yafti.gtk || true

# Run yafti-gtk from the installed flatpak with default config
run yml="/run/host/usr/share/yafti/yafti.yml":
    flatpak run com.github.yafti.gtk {{yml}}

# Set up flatpak-builder from Flathub
setup:
    flatpak install --user -y flathub org.flatpak.Builder
    flatpak install --user -y flathub org.gnome.Platform//48 org.gnome.Sdk//48

# Clean build artifacts
clean:
    rm -rf .flatpak-builder build-dir repo
    rm -f yafti-gtk.flatpak
