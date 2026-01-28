# Bazzite Portal

![Bazzite Portal Screenshot](assets/demo.gif)


A GTK3 interface for the Bazzite Portal, providing quick access to various useful scripts, fixes, and QOL tweaks for the terminal averse.

The default configuration file is located at:
```
/usr/share/yafti/yafti.yml
```

## Installing

Note: this application will soon be published in the Terra repository, once available, prefer installing from Terra. Until then, run the app from source as shown in the sections bellow.

## Running

The application requires a YAML configuration file path as a command-line argument.

### On Bazzite (default config)

```bash
yafti_gtk.py /usr/share/yafti/yafti.yml
```

### With Custom Config

```bash
yafti_gtk.py /path/to/custom/yafti.yml
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
