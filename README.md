# Home Assistant Custom Commands – Unfolded Circle Remote 3

Standalone custom integration for the Unfolded Circle Remote 3. This project is intentionally independent from the built-in Home Assistant integration.

## What it provides

The driver exposes exactly one Remote entity:

```text
Geräte
└── Stehlampe
    ├── EIN/AUS
    ├── HELLER
    ├── DUNKLER
    └── MODUS
```

The entity also publishes its own UI page with those four controls. No activity is required.

The physical Remote 3 volume keys are mapped to:

```text
VOL+ → HELLER
VOL− → DUNKLER
```

The implementation uses the official Unfolded Circle Integration API and its Remote entity support for simple commands, physical button mappings and UI pages.

## Home Assistant side

The driver calls Home Assistant directly through the WebSocket API and invokes the `remote.send_command` service with the same values as the existing scripts:

```yaml
action: remote.send_command
target:
  entity_id: remote.broadlink
data:
  delay_secs: 0.4
  hold_secs: 0
  device: Stehlampe
  command: <COMMAND>
```

The four Home Assistant commands are:

- `EIN/AUS`
- `HELLER`
- `DUNKLER`
- `MODUS`

The previous four Home Assistant scripts are therefore no longer required once this integration is working.

## Setup

During integration setup on the Remote 3 / web configurator, enter:

- Home Assistant URL, for example `http://homeassistant.local:8123`
- Home Assistant Long-Lived Access Token
- Home Assistant remote entity, default `remote.broadlink`
- Remote device name, default `Stehlampe`
- Command delay, default `0.4` seconds

The driver authenticates with Home Assistant and verifies that the configured remote entity exists before completing setup.

The access token is **not** stored in the GitHub repository. It is stored only in the integration's runtime configuration on the Remote.

## Build

The GitHub Actions workflow builds an ARM64/aarch64 installation archive with the official Unfolded Circle PyInstaller image.

After pushing to `main` or starting the workflow manually:

1. Open the repository's **Actions** tab.
2. Select **Build Remote 3 Integration**.
3. Download the artifact `uc-intg-homeassistantcustom-aarch64`.
4. Use the contained `uc-intg-homeassistantcustom-aarch64.tar.gz` in the Remote 3 custom-integration installer.

The archive has the expected custom-integration structure with `driver.json` at the root and the compiled driver below `bin/driver`.

## Development

Runtime dependencies are kept in `requirements.txt`. The repository does not contain a device-specific Home Assistant token or other secret configuration.

## License

This project is provided as-is for use with the author's Remote 3 setup.
