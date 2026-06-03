# Hanshow Codex Usage Monitor

Generate a Hanshow 2.13" BWR e-paper payload that shows the current Codex usage quota, then optionally upload it to the tag over BLE.

The generated screen is 212x104 pixels:

- red bar/text: remaining 5-hour Codex quota
- black bar/text: remaining 1-week Codex quota
- reset labels: 5-hour reset time and weekly reset date

## Files

- `update_codex_payload.py` - main script. Fetches Codex usage, renders the 212x104 image, writes `codex_usage.bin`, and can upload it over BLE.
- `MatrixSans-Regular.ttf` - font used by the generated screen.
- `bin_debugger.html` - browser debugger for opening `*.bin`, previewing every packet step, and optionally writing through Web Bluetooth.
- `serialize.py` - converts a 212x104 BMP into a Hanshow BLE payload bin.
- `codex_usage.bin` - latest generated BLE payload.
- `example/` - example output files.

## Requirements

Before using this project, the BLE e-paper tag must be flashed with the [`ihopenot/ihopebleepd`](https://github.com/ihopenot/ihopebleepd.git) firmware. That firmware provides the BLE UART service and e-paper write protocol used here.

Python:

```powershell
python -m pip install pillow bleak
```

The Codex usage script reads the local Codex login token from your Codex home:

```text
%USERPROFILE%\.codex\auth.json
```

It calls:

```text
https://chatgpt.com/backend-api/wham/usage
```

The API returns used percentage values, so the script displays `100 - used_percent` as remaining quota.

## Generate The Usage Payload

From this directory:

```powershell
python update_codex_payload.py --output codex_usage.bin --preview codex_usage.bmp
```

This writes:

- `codex_usage.bin` - raw BLE write packets concatenated together
- `codex_usage.bmp` - preview image

Demo values:

```powershell
python update_codex_payload.py --demo --output codex_usage.bin --preview codex_usage.bmp
```

Color modes:

```powershell
python update_codex_payload.py --color-mode bwr
python update_codex_payload.py --color-mode bw
```

`bwr` is the default and renders the 5-hour quota in red. `bw` renders everything in black and white and outputs a BW-only payload without the red plane.

Text uses the regular font weight by default. To render both text rows in bold:

```powershell
python update_codex_payload.py --bold
```

Manual values:

```powershell
python update_codex_payload.py --five-hour-percent 99 --five-hour-reset 19:06 --week-percent 92 --week-reset "Jun 08"
```

JSON input is also supported:

```powershell
python update_codex_payload.py --usage-json usage.json
```

Example JSON:

```json
{
  "5h": { "percent": 99, "reset": "19:06" },
  "1wk": { "percent": 92, "reset": "Jun 08" }
}
```

## Upload Over BLE

To generate and upload in one command:

```powershell
python update_codex_payload.py --upload
```

The script scans by advertised device name, then connects to the UART service:

- device names: `Ihopeseral_uarttrans`, `SPP BLE Server`
- service UUID: `f000fff0-0451-4000-b000-000000000000`
- characteristic UUID: `f000fff1-0451-4000-b000-000000000000`

Each packet is written with response. The script waits for notification ACKs after each packet except the final display-update command.

Useful options:

```powershell
python update_codex_payload.py --upload --ble-scan-timeout 60000
python update_codex_payload.py --upload --ble-name "SPP BLE Server"
```

## Debug A Bin File

Open `bin_debugger.html` from the project root in a browser with Web Bluetooth support.

For example, from this directory:

```powershell
start .\bin_debugger.html
```

Use it to:

- open `codex_usage.bin` or `image.bin`
- inspect the packet timeline
- preview clear/init/BW/red/update steps
- connect to the BLE tag from the browser
- write the current bin to the device

## Convert A BMP To Payload

`serialize.py` converts a 212x104 BMP into the same raw BLE packet format:

```powershell
python serialize.py input.bmp image.bin
```

Options:

```powershell
python serialize.py input.bmp image.bin --mode=auto
python serialize.py input.bmp image.bin --mode=bwr --threshold=128 --red-threshold=160 --red-delta=50
python serialize.py input.bmp image.bin --records
```

Supported BMP depths include 1/4/8/16/24/32-bit uncompressed BMPs. Red pixels are sent in the red plane, and red positions are excluded from the black/white plane.

## Payload Format

The default output is raw concatenated BLE writes:

```text
01 ff        clear screen to white
00 02        initialize BWR mode
04           prepare black/white RAM
02 ...       black/white image chunks, up to 200 payload bytes each
05           prepare red RAM
02 ...       red image chunks, up to 200 payload bytes each
03           display update
```

The image payload is packed as column-major 212x104 bits.

## Notes

- The generated image uses `MatrixSans-Regular.ttf` when present in the project root.
- `codex_usage.bmp` is only a preview; the file uploaded to the tag is `codex_usage.bin`.
- If Python BLE scanning cannot find the device, try the browser debugger first to confirm the device is advertising and connectable.
