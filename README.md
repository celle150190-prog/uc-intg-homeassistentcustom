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

The entity publishes its own UI page with those four controls. No activity is required.

The physical Remote 3 volume keys are mapped to:

```text
VOL+ → HELLER
VOL− → DUNKLER
```

## Home Assistant side

The driver calls the Home Assistant REST API and invokes the `remote.send_command` service with the same values used by the existing scripts:

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

The four commands are:

- `EIN/AUS`
- `HELLER`
- `DUNKLER`
- `MODUS`

The previous four Home Assistant scripts are therefore not required for the Remote once this integration is working.

## Setup

Enter the following values in the Remote 3 / web configurator:

- Home Assistant URL, for example `http://homeassistant.local:8123`
- Home Assistant Long-Lived Access Token
- Home Assistant remote entity, default `remote.broadlink`
- Remote device name, default `Stehlampe`
- Command delay, default `0.4` seconds

The setup flow only validates and stores the configuration. It deliberately does **not** contact Home Assistant while the integration is being installed. This prevents a temporary Home Assistant/network problem from aborting Remote 3 integration setup.

The Home Assistant REST request is performed when a lamp command is executed. Errors are written to the integration log and returned as a failed command.

The access token is not stored in the GitHub repository. It is stored only in the integration's runtime configuration on the Remote.

## Network and driver port

The Remote 3 custom-integration runtime supplies the Integration API port through `UC_INTEGRATION_HTTP_PORT`. The metadata therefore does not hard-code a port. For local/manual execution only, the driver uses port `19123` as a fallback when the runtime variable is not present.

## Build

The GitHub Actions workflow builds an ARM64/aarch64 installation archive with the official Unfolded Circle PyInstaller image.

After pushing to `main` or starting the workflow manually:

1. Open the repository's **Actions** tab.
2. Select **Build Remote 3 Integration**.
3. Download the artifact `uc-intg-homeassistantcustom-aarch64`.
4. Use the contained `uc-intg-homeassistantcustom-aarch64.tar.gz` in the Remote 3 custom-integration installer.

The archive is validated to contain `driver.json` at the root and the compiled executable at `./bin/driver`.

## Development

Runtime dependencies are kept in `requirements.txt`. The repository does not contain a device-specific Home Assistant token or other secret configuration.

## License

This project is provided as-is for use with the author's Remote 3 setup.
