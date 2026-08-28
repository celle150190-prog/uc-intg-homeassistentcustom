# Home Assistant Custom Commands – Unfolded Circle Remote 3

Standalone custom integration driver for the Unfolded Circle Remote 3.

The integration exposes one Remote entity named **Stehlampe** with four simple commands:

- EIN/AUS
- HELLER
- DUNKLER
- MODUS

The commands are forwarded to Home Assistant using the `remote.send_command` service on `remote.broadlink`, matching the user's existing Home Assistant setup.

The Remote 3 physical volume buttons are intended to be mapped as:

- Volume Up → HELLER
- Volume Down → DUNKLER

This project is intentionally a standalone custom integration and is **not** an upgrade/update package for the built-in Home Assistant integration.

## Requirements

- Unfolded Circle Remote 3
- Home Assistant reachable from the Remote 3
- Python 3.11+ when running externally
- `ucapi` 0.7.0

## Home Assistant

The driver targets the existing Home Assistant remote entity:

`remote.broadlink`

Each command is sent as:

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

where `<COMMAND>` is one of `EIN/AUS`, `HELLER`, `DUNKLER`, or `MODUS`.

## Installation

Build/run the integration as a normal Unfolded Circle custom integration driver. The driver metadata is in `driver.json`.
