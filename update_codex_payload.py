#!/usr/bin/env python3
"""Render Codex 5h/1wk usage as an e-paper payload bin."""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFont


WIDTH = 212
HEIGHT = 104
IMAGE_BYTES = (WIDTH * HEIGHT) // 8
CHUNK_BYTES = 200
BLE_DEVICE_NAMES = ["Ihopeseral_uarttrans", "SPP BLE Server", "Octppus_uarttrans"]
BLE_SERVICE_UUID = "f000fff0-0451-4000-b000-000000000000"
BLE_CHARACTERISTIC_UUID = "f000fff1-0451-4000-b000-000000000000"
BLE_ACK_TIMEOUT_MS = 10000
BLE_SCAN_TIMEOUT_MS = 30000

BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
RED = (255, 0, 0)
PROJECT_ROOT = Path(__file__).resolve().parent
MATRIX_SANS_PATH = PROJECT_ROOT / "MatrixSans-Regular.ttf"
DEFAULT_CODEX_HOME = Path.home() / ".codex"
DEFAULT_USAGE_API_URL = "https://chatgpt.com/backend-api/wham/usage"


@dataclass(frozen=True)
class UsageWindow:
    label: str
    percent: float
    reset: str


@dataclass(frozen=True)
class UsageSnapshot:
    five_hour: UsageWindow
    week: UsageWindow
    source: str


def parse_percent(value: Any, name: str) -> float:
    if value is None or value == "":
        raise ValueError(f"{name} is required")

    text = str(value).strip()
    had_percent = text.endswith("%")
    if had_percent:
        text = text[:-1].strip()

    percent = float(text)
    if not had_percent and 0 <= percent <= 1:
        percent *= 100
    return max(0.0, min(100.0, percent))


def parse_usage_json(text_or_path: str) -> dict[str, Any]:
    candidate = Path(text_or_path)
    if candidate.exists():
        return json.loads(candidate.read_text(encoding="utf-8"))
    return json.loads(text_or_path)


def pick(data: dict[str, Any], names: list[str]) -> Any:
    for name in names:
        if name in data and data[name] not in (None, ""):
            return data[name]
    return None


def nested_window(
    data: dict[str, Any],
    object_names: list[str],
    percent_names: list[str],
    reset_names: list[str],
) -> tuple[Any, Any]:
    for object_name in object_names:
        value = data.get(object_name)
        if isinstance(value, dict):
            percent = pick(value, ["percent", "percentage", "used_percent", "usage_percent", "usage"])
            reset = pick(value, ["reset", "reset_at", "reset_time", "reset_label"])
            if percent is not None or reset is not None:
                return percent, reset

    return pick(data, percent_names), pick(data, reset_names)


def usage_from_json(data: dict[str, Any]) -> UsageSnapshot:
    five_percent, five_reset = nested_window(
        data,
        ["5h", "five_hour", "fiveHour", "five_hours", "rolling_5h"],
        ["5h_percent", "five_hour_percent", "fiveHourPercent", "codex_5h_percent"],
        ["5h_reset", "five_hour_reset", "fiveHourReset", "codex_5h_reset"],
    )
    week_percent, week_reset = nested_window(
        data,
        ["1wk", "week", "one_week", "weekly", "rolling_1wk"],
        ["1wk_percent", "week_percent", "one_week_percent", "codex_1wk_percent"],
        ["1wk_reset", "week_reset", "one_week_reset", "codex_1wk_reset"],
    )

    return UsageSnapshot(
        five_hour=UsageWindow("5h", parse_percent(five_percent, "5h percent"), str(five_reset or "")),
        week=UsageWindow("1wk", parse_percent(week_percent, "1wk percent"), str(week_reset or "")),
        source="json",
    )


def usage_from_env() -> UsageSnapshot | None:
    five_percent = os.environ.get("CODEX_5H_PERCENT")
    week_percent = os.environ.get("CODEX_1WEEK_PERCENT")
    if not five_percent and not week_percent:
        return None

    return UsageSnapshot(
        five_hour=UsageWindow("5h", parse_percent(five_percent, "CODEX_5H_PERCENT"), os.environ.get("CODEX_5H_RESET", "")),
        week=UsageWindow("1wk", parse_percent(week_percent, "CODEX_1WEEK_PERCENT"), os.environ.get("CODEX_1WEEK_RESET", "")),
        source="env",
    )


def auth_token_from_codex_home(codex_home: Path) -> str:
    auth_path = codex_home / "auth.json"
    data = json.loads(auth_path.read_text(encoding="utf-8"))
    token = data.get("tokens", {}).get("access_token") or data.get("OPENAI_API_KEY")
    if not token:
        raise RuntimeError(f"No access token found in {auth_path}")
    return str(token)


def reset_time_label(reset_at: Any, fallback_seconds: Any, style: str) -> str:
    if reset_at:
        target = dt.datetime.fromtimestamp(int(reset_at))
    else:
        target = dt.datetime.now() + dt.timedelta(seconds=int(fallback_seconds or 0))

    if style == "time":
        return target.strftime("%H:%M")
    return target.strftime("%b %d")


def parse_api_percent(value: Any, name: str) -> float:
    if value is None or value == "":
        raise ValueError(f"{name} is required")
    text = str(value).strip()
    if text.endswith("%"):
        text = text[:-1].strip()
    return max(0.0, min(100.0, float(text)))


def remaining_percent(used_percent: Any, name: str) -> float:
    return 100.0 - parse_api_percent(used_percent, name)


def usage_from_api(args: argparse.Namespace) -> UsageSnapshot:
    token = args.api_token or os.environ.get("CODEX_USAGE_TOKEN") or auth_token_from_codex_home(Path(args.codex_home))
    request = Request(
        args.api_url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
    )

    try:
        with urlopen(request, timeout=args.api_timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"Codex usage API returned HTTP {exc.code}: {args.api_url}") from exc

    rate_limit = data.get("rate_limit") or data
    primary = rate_limit.get("primary_window") or {}
    secondary = rate_limit.get("secondary_window") or {}
    if not primary or not secondary:
        raise RuntimeError("Codex usage API response does not contain primary_window/secondary_window")

    return UsageSnapshot(
        five_hour=UsageWindow(
            "5h",
            remaining_percent(primary.get("used_percent"), "primary_window.used_percent"),
            reset_time_label(primary.get("reset_at"), primary.get("reset_after_seconds"), "time"),
        ),
        week=UsageWindow(
            "1wk",
            remaining_percent(secondary.get("used_percent"), "secondary_window.used_percent"),
            reset_time_label(secondary.get("reset_at"), secondary.get("reset_after_seconds"), "date"),
        ),
        source="api",
    )


def get_usage(args: argparse.Namespace) -> UsageSnapshot:
    if args.demo:
        return UsageSnapshot(
            five_hour=UsageWindow("5h", 50, "14:00"),
            week=UsageWindow("1wk", 90, "Jun 08"),
            source="demo",
        )

    if args.usage_json or os.environ.get("CODEX_USAGE_JSON"):
        return usage_from_json(parse_usage_json(args.usage_json or os.environ["CODEX_USAGE_JSON"]))

    cli_values = [args.five_hour_percent, args.five_hour_reset, args.week_percent, args.week_reset]
    if any(value not in (None, "") for value in cli_values):
        return UsageSnapshot(
            five_hour=UsageWindow("5h", parse_percent(args.five_hour_percent, "--five-hour-percent"), args.five_hour_reset),
            week=UsageWindow("1wk", parse_percent(args.week_percent, "--week-percent"), args.week_reset),
            source="cli",
        )

    env_usage = usage_from_env()
    if env_usage:
        return env_usage

    return usage_from_api(args)


def find_font(names: list[str], size: int) -> ImageFont.ImageFont:
    windir = os.environ.get("WINDIR")
    if not windir:
        return ImageFont.load_default()
    font_dir = Path(windir) / "Fonts"
    for name in names:
        path = font_dir / name
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def load_text_font(size: int) -> ImageFont.ImageFont:
    if MATRIX_SANS_PATH.exists():
        return ImageFont.truetype(str(MATRIX_SANS_PATH), size)
    return find_font(["arial.ttf", "segoeui.ttf", "consola.ttf"], size)


def text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, stroke_width: int = 0) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    return box[2] - box[0], box[3] - box[1]


def draw_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int],
    stroke_width: int = 0,
) -> None:
    draw.text(xy, text, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=fill)


def draw_right(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int],
    stroke_width: int = 0,
) -> None:
    width, _ = text_size(draw, text, font, stroke_width=stroke_width)
    draw_text(draw, (x - width, y), text, font, fill, stroke_width=stroke_width)


def draw_dithered_rect(
    draw: ImageDraw.ImageDraw,
    rect: tuple[int, int, int, int],
    fill: tuple[int, int, int] = BLACK,
) -> None:
    x1, y1, x2, y2 = rect
    for y in range(y1, y2 + 1):
        for x in range(x1, x2 + 1):
            if (x + y) % 2 == 0:
                draw.point((x, y), fill=fill)


def render_usage_image(snapshot: UsageSnapshot, color_mode: str) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(image)

    font = load_text_font(18)
    five_color = RED if color_mode == "bwr" else BLACK

    frame = (2, 2, 209, 40)
    frame_inner = (7, 7, 204, 36)
    five_bar = (9, 9, 204, 20)
    week_bar = (9, 24, 204, 34)

    draw_dithered_rect(draw, frame)
    draw.rectangle(frame_inner, fill=WHITE)

    five_width = int(round((five_bar[2] - five_bar[0] + 1) * snapshot.five_hour.percent / 100))
    week_width = int(round((week_bar[2] - week_bar[0] + 1) * snapshot.week.percent / 100))
    if five_width > 0:
        draw.rectangle((five_bar[0], five_bar[1], five_bar[0] + five_width - 1, five_bar[3]), fill=five_color)
    if week_width > 0:
        draw.rectangle((week_bar[0], week_bar[1], week_bar[0] + week_width - 1, week_bar[3]), fill=BLACK)

    five_percent = f"{round(snapshot.five_hour.percent):d}%"
    week_percent = f"{round(snapshot.week.percent):d}%"

    draw_text(draw, (4, 48), snapshot.five_hour.label, font, five_color)
    draw_text(draw, (43, 48), five_percent, font, five_color)
    draw_right(draw, 208, 48, snapshot.five_hour.reset, font, five_color)

    draw_text(draw, (4, 82), snapshot.week.label, font, BLACK)
    draw_text(draw, (43, 82), week_percent, font, BLACK)
    draw_right(draw, 208, 82, snapshot.week.reset, font, BLACK)

    return image


def is_red(pixel: tuple[int, int, int]) -> bool:
    r, g, b = pixel
    return r >= 160 and r - g >= 50 and r - b >= 50


def pack_plane(image: Image.Image, plane: str) -> bytes:
    out: list[int] = []
    bits: list[str] = []
    pixels = image.load()

    for x in range(WIDTH):
        for y in range(HEIGHT):
            r, g, b = pixels[x, y]
            red = is_red((r, g, b))
            if plane == "red":
                bit = 1 if red else 0
            else:
                luminance = 0.299 * r + 0.587 * g + 0.114 * b
                bit = 1 if (not red and luminance >= 128) else 0
            bits.append("1" if bit else "0")
            if len(bits) == 8:
                out.append(int("".join(bits), 2))
                bits.clear()

    if bits:
        out.append(int("".join(bits).ljust(8, "0"), 2))
    if len(out) != IMAGE_BYTES:
        raise ValueError(f"expected {IMAGE_BYTES} packed bytes, got {len(out)}")
    return bytes(out)


def append_image_packets(packets: list[bytes], command: int, payload: bytes) -> None:
    packets.append(bytes([command]))
    for offset in range(0, len(payload), CHUNK_BYTES):
        packets.append(bytes([0x02]) + payload[offset : offset + CHUNK_BYTES])


def build_payload(image: Image.Image, color_mode: str) -> bytes:
    bw = pack_plane(image, "bw")
    init_mode = 0x02 if color_mode == "bwr" else 0x01
    packets: list[bytes] = [bytes([0x01, 0xFF]), bytes([0x00, init_mode])]
    append_image_packets(packets, 0x04, bw)
    if color_mode == "bwr":
        red = pack_plane(image, "red")
        append_image_packets(packets, 0x05, red)
    packets.append(bytes([0x03]))
    return b"".join(packets)


def is_known_packet_start(packet: bytes) -> bool:
    return len(packet) > 0 and packet[0] in {0x00, 0x01, 0x02, 0x03, 0x04, 0x05}


def try_read_records(data: bytes) -> list[bytes] | None:
    packets: list[bytes] = []
    cursor = 0
    while cursor + 2 <= len(data):
        packet_len = data[cursor] | (data[cursor + 1] << 8)
        if packet_len < 1 or packet_len > 512 or cursor + 2 + packet_len > len(data):
            return None
        packets.append(data[cursor + 2 : cursor + 2 + packet_len])
        cursor += 2 + packet_len

    if cursor != len(data) or not packets or not is_known_packet_start(packets[0]):
        return None
    return packets


def read_raw_packets(data: bytes) -> list[bytes]:
    packets: list[bytes] = []
    cursor = 0
    active_plane = ""
    remaining = 0

    while cursor < len(data):
        cmd = data[cursor]
        packet_len = 1

        if cmd in {0x00, 0x01}:
            packet_len = 2
        elif cmd in {0x04, 0x05, 0x03}:
            packet_len = 1
        elif cmd == 0x02:
            if not active_plane or remaining <= 0:
                raise ValueError(f"offset {cursor}: data packet without active image plane")
            packet_len = 1 + min(CHUNK_BYTES, remaining)
        else:
            raise ValueError(f"offset {cursor}: unknown command 0x{cmd:02x}")

        if cursor + packet_len > len(data):
            raise ValueError(f"offset {cursor}: truncated packet")

        packet = data[cursor : cursor + packet_len]
        packets.append(packet)

        if cmd == 0x04:
            active_plane = "bw"
            remaining = IMAGE_BYTES
        elif cmd == 0x05:
            active_plane = "red"
            remaining = IMAGE_BYTES
        elif cmd == 0x02:
            remaining -= packet_len - 1
            if remaining == 0:
                active_plane = ""

        cursor += packet_len

    return packets


def parse_image_bin(data: bytes) -> tuple[list[bytes], str]:
    records = try_read_records(data)
    if records is not None:
        return records, "records"
    return read_raw_packets(data), "raw"


def describe_packet(packet: bytes) -> str:
    if len(packet) == 2 and packet[0] == 0x01:
        return "clear white" if packet[1] == 0xFF else f"clear 0x{packet[1]:02x}"
    if len(packet) == 2 and packet[0] == 0x00:
        return "init BWR" if packet[1] == 0x02 else "init BW"
    if packet[0] == 0x04:
        return "prepare BW RAM"
    if packet[0] == 0x05:
        return "prepare red RAM"
    if packet[0] == 0x02:
        return f"data {len(packet) - 1} bytes"
    if packet[0] == 0x03:
        return "display update"
    return f"cmd 0x{packet[0]:02x}"


def load_bleak() -> tuple[Any, Any]:
    try:
        from bleak import BleakClient, BleakScanner
    except ImportError as exc:
        raise RuntimeError("Missing BLE dependency: install it with `python -m pip install bleak`") from exc
    return BleakClient, BleakScanner


async def wait_for_ble_ack(ack_queue: asyncio.Queue[bytes], timeout_seconds: float) -> bytes:
    return await asyncio.wait_for(ack_queue.get(), timeout=timeout_seconds)


async def upload_packets(args: argparse.Namespace, packets: list[bytes]) -> None:
    BleakClient, BleakScanner = load_bleak()
    names = [name.strip() for name in args.ble_name if name.strip()]
    scan_timeout = args.ble_scan_timeout / 1000
    ack_timeout = args.ble_ack_timeout / 1000

    print(f"Scanning for {', '.join(names)}...")
    # Match the Web Bluetooth page: filter by advertised name first, then ask
    # for the GATT service after connecting. These tags do not always include
    # the UART service UUID in advertising packets, so service-filtered scans
    # can miss devices that the browser can see.
    devices = await BleakScanner.discover(timeout=scan_timeout, return_adv=True)
    seen_names: set[str] = set()
    device = None
    for ble_device, advertisement in devices.values():
        advertised_name = advertisement.local_name or ble_device.name or ""
        if advertised_name:
            seen_names.add(advertised_name)
        if advertised_name in names:
            device = ble_device
            break

    if device is None:
        seen = ", ".join(sorted(seen_names)) or "no named BLE devices"
        raise RuntimeError(f"Target BLE device not found. Saw: {seen}")

    print(f"Connecting {device.name or '(no name)'} {device.address}...")
    ack_queue: asyncio.Queue[bytes] = asyncio.Queue()

    def on_notify(_sender: Any, data: bytearray) -> None:
        ack_queue.put_nowait(bytes(data))

    async with BleakClient(device) as client:
        await client.start_notify(args.ble_characteristic_uuid, on_notify)
        try:
            for index, packet in enumerate(packets, start=1):
                while not ack_queue.empty():
                    ack_queue.get_nowait()
                print(f"[{index:02d}/{len(packets)}] write {describe_packet(packet)}")
                await client.write_gatt_char(args.ble_characteristic_uuid, packet, response=True)
                if index == len(packets):
                    print(f"[{index:02d}/{len(packets)}] final packet sent")
                    continue
                ack = await wait_for_ble_ack(ack_queue, ack_timeout)
                print(f"[{index:02d}/{len(packets)}] ack {ack.hex()}")
        finally:
            await client.stop_notify(args.ble_characteristic_uuid)

    print("Upload complete")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Codex 5h/1wk usage progress bar and output BLE payload bin.")
    parser.add_argument("--output", default="codex_usage.bin", help="output BLE payload bin")
    parser.add_argument("--preview", default="", help="optional preview BMP path")
    parser.add_argument("--demo", action="store_true", help="render sample values matching progressbar.bmp")
    parser.add_argument("--usage-json", default="", help="JSON string or path containing 5h and 1wk usage fields")
    parser.add_argument("--color-mode", choices=["bwr", "bw"], default="bwr", help="display/output color mode: bwr uses red, bw is black/white only")
    parser.add_argument("--five-hour-percent", default="", help="5h usage percent, e.g. 50 or 50%")
    parser.add_argument("--five-hour-reset", default="", help="5h reset label, e.g. 14:00")
    parser.add_argument("--week-percent", default="", help="1wk usage percent, e.g. 90 or 90%")
    parser.add_argument("--week-reset", default="", help="1wk reset label, e.g. Jun 08")
    parser.add_argument("--api-url", default=DEFAULT_USAGE_API_URL, help="Codex usage API endpoint")
    parser.add_argument("--api-token", default="", help="override API bearer token; otherwise uses CODEX_USAGE_TOKEN or ~/.codex/auth.json")
    parser.add_argument("--api-timeout", type=int, default=20, help="Codex usage API timeout seconds")
    parser.add_argument("--codex-home", default=str(DEFAULT_CODEX_HOME), help="Codex home containing auth.json")
    parser.add_argument("--upload", action="store_true", help="upload the generated payload to the BLE e-paper tag")
    parser.add_argument("--ble-name", action="append", default=BLE_DEVICE_NAMES, help="allowed BLE device name; can be repeated")
    parser.add_argument("--ble-service-uuid", default=BLE_SERVICE_UUID, help="BLE GATT service UUID")
    parser.add_argument("--ble-characteristic-uuid", default=BLE_CHARACTERISTIC_UUID, help="BLE GATT characteristic UUID")
    parser.add_argument("--ble-scan-timeout", type=int, default=BLE_SCAN_TIMEOUT_MS, help="BLE scan timeout in milliseconds")
    parser.add_argument("--ble-ack-timeout", type=int, default=BLE_ACK_TIMEOUT_MS, help="BLE ACK timeout in milliseconds")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    snapshot = get_usage(args)
    image = render_usage_image(snapshot, args.color_mode)
    payload = build_payload(image, args.color_mode)

    Path(args.output).write_bytes(payload)
    if args.preview:
        image.save(args.preview)

    print(
        f"source={snapshot.source} "
        f"color_mode={args.color_mode} "
        f"5h={snapshot.five_hour.percent:.0f}% reset={snapshot.five_hour.reset} "
        f"1wk={snapshot.week.percent:.0f}% reset={snapshot.week.reset}"
    )
    print(f"wrote {args.output} ({len(payload)} bytes)")
    if args.preview:
        print(f"wrote preview {args.preview}")

    if args.upload:
        packets, payload_format = parse_image_bin(payload)
        print(f"uploading {len(packets)} packets ({payload_format} format)")
        try:
            asyncio.run(upload_packets(args, packets))
        except RuntimeError as exc:
            print(f"upload error: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
