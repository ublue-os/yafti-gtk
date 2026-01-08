# Bazzite Portal

A GTK3 interface for the Bazzite Portal, providing quick access to system utilities, updates, and rebasing tools.

**Note:** This application is designed specifically for [Bazzite](https://bazzite.gg/) - a custom Fedora-based Linux image for gaming and content creation. It integrates with Bazzite-specific tools like `ujust` and `brh` (Bazzite Rollback Helper).

## Features

- **Tabbed interface** with organized system utilities
- **Live search** for quick access to actions
- **System management** tools (updates, rebasing)
- **Host terminal integration** with automatic fallback
- **YAML-based configuration**

## For Bazzite Users

On Bazzite systems, the portal should be pre-installed and available in your application menu as "Bazzite Portal". Simply launch it from your desktop environment.

The default configuration file is located at:
```
/usr/share/yafti/yafti.yml
```

## Building from Source

### Using Dev Container (Recommended)

The project includes a `.devcontainer` configuration for consistent development environment:

1. Open the project in VS Code
2. Click "Reopen in Container" when prompted (or use Command Palette: "Dev Containers: Reopen in Container")
3. Build the Flatpak inside the container:

```bash
flatpak-builder --user --install --force-clean build-dir com.github.yafti.gtk.yml
```

The container includes all required dependencies (Flatpak, flatpak-builder, org.gnome.Platform/Sdk 48).

### Manual Build

#### Requirements

- Flatpak
- flatpak-builder
- org.gnome.Platform runtime (version 48)

#### Build and Install

Build and install the Flatpak locally:

```bash
flatpak-builder --user --install --force-clean build-dir com.github.yafti.gtk.yml
```

For development (build only, no install):

```bash
flatpak-builder --force-clean build-dir com.github.yafti.gtk.yml
```

## Running

The application requires a YAML configuration file path as a command-line argument.

### On Bazzite (default config)

```bash
flatpak run com.github.yafti.gtk /run/host/usr/share/yafti/yafti.yml
```

### With Custom Config

```bash
flatpak run com.github.yafti.gtk /path/to/custom/yafti.yml
```

### Desktop Shortcut

The installed desktop file automatically launches with the default Bazzite config path. You can find it in your application menu as "Bazzite Portal".

## Configuration

The app reads a `yafti.yml` configuration file to populate tabs and actions. The YAML file should follow this structure:

```yaml
screens:
  - title: "Category Name"
    actions:
      - title: "Action Title"
        description: "Optional description"
        script: "command to run"
```

See the [yafti](https://github.com/ublue-os/yafti) project for full config format details.

### Example Config Location on Bazzite

- **System config**: `/usr/share/yafti/yafti.yml` (inside Flatpak: `/run/host/usr/share/yafti/yafti.yml`)
- **Custom config**: Can be placed anywhere accessible to the Flatpak

## Terminal Integration

Actions run in the host terminal using `flatpak-spawn --host` with the following fallback chain:

1. **ptyxis** (KDE Plasma terminal, default on Bazzite)
2. **konsole** (KDE terminal)
3. **gnome-terminal** (GNOME terminal)
4. **xterm** (universal fallback)

If no host terminal is available, commands run in an embedded VTE terminal dialog within the app.

## License

See LICENSE file for details.

## Exporting the Flatpak from a Docker Volume (Linux)

If you run the devcontainer in Docker using a named volume (or without a host bind), the built bundle will live inside the container filesystem or volume. Use one of these methods to copy `output/yafti-gtk.flatpak` to your home directory.

- From a running container (simplest):

```bash
# find the container id
docker ps
# copy the bundle to your home directory
docker cp <container-id>:/workspaces/yafti-gtk/output/yafti-gtk.flatpak ~/
```

- From a named Docker volume (no running container):

```bash
# replace VOLUME with your volume name
docker run --rm -v VOLUME:/data -v "$HOME":/host alpine \
  sh -c "cp /data/output/yafti-gtk.flatpak /host/"
```

- Alternative (mount volume to temporary container and inspect):

```bash
docker run --rm -it -v VOLUME:/data alpine sh
ls /data/output
exit
```

After copying, the file will be available at `~/yafti-gtk.flatpak` (or whatever destination you chose). You can then install it on a Linux machine with:

```bash
flatpak install --user ~/yafti-gtk.flatpak
```
