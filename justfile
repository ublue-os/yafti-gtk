_default:
    @just --list

container := "flatpak-builder"

# Build the flatpak inside the distrobox container
build:
    @distrobox list | grep -q "{{container}}" || just setup
    -distrobox enter {{container}} -- bash -c 'rm -rf .flatpak-builder' || sudo rm -rf .flatpak-builder
    distrobox enter {{container}} -- bash -c './build-flatpak.sh'
    @test -f output/yafti-gtk.flatpak && echo "✓ Flatpak built successfully" || (echo "✗ Build failed - flatpak not found" && exit 1)

# Install the built flatpak
install:
    @test -f output/yafti-gtk.flatpak || (echo "✗ output/yafti-gtk.flatpak not found - run 'just build' first" && exit 1)
    flatpak install --user -y output/yafti-gtk.flatpak

# Uninstall the flatpak
uninstall:
    flatpak uninstall --user -y com.github.yafti.gtk || true

# Run yafti-gtk from the installed flatpak with default config
run yml="/run/host/usr/share/yafti/yafti.yml":
    flatpak run com.github.yafti.gtk {{yml}}

# Set up distrobox container with dependencies
setup:
    distrobox create --name {{container}} --image fedora:latest
    distrobox enter {{container}} -- bash -c 'sudo dnf install -y flatpak-builder && flatpak remote-add --if-not-exists --user flathub https://flathub.org/repo/flathub.flatpakrepo && flatpak install -y --user org.gnome.Platform//48 org.gnome.Sdk//48'

# Clean build artifacts
clean:
    -distrobox enter {{container}} -- bash -c 'rm -rf .flatpak-builder build-dir output repo' 2>/dev/null || sudo rm -rf .flatpak-builder build-dir output repo

# Remove distrobox container
destroy:
    distrobox rm -f {{container}}
