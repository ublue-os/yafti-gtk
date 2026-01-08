# Build yafti-gtk flatpak in distrobox

container := "flatpak-builder"

build:
    @distrobox list | grep -q "{{container}}" || just setup
    -distrobox enter {{container}} -- bash -c 'rm -rf .flatpak-builder' || sudo rm -rf .flatpak-builder
    distrobox enter {{container}} -- bash -c './build-flatpak.sh'
    @test -f output/yafti-gtk.flatpak && echo "✓ Flatpak built successfully" || (echo "✗ Build failed - flatpak not found" && exit 1)

install:
    @test -f output/yafti-gtk.flatpak || (echo "✗ output/yafti-gtk.flatpak not found - run 'just build' first" && exit 1)
    flatpak install --user -y output/yafti-gtk.flatpak

run:
    flatpak run com.github.yafti.gtk /run/host/usr/share/yafti/yafti.yml

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
