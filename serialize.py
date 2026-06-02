#!/usr/bin/env python3
"""Convert a 212x104 BMP into Hanshow BLE payload bytes."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path


WIDTH = 212
HEIGHT = 104
IMAGE_BYTES = (WIDTH * HEIGHT) // 8
BLE_PAYLOAD_BYTES = 200


@dataclass(frozen=True)
class Rgb:
    r: int
    g: int
    b: int


@dataclass(frozen=True)
class BitMasks:
    r: int
    g: int
    b: int


@dataclass(frozen=True)
class BmpInfo:
    data: bytes
    pixel_offset: int
    width: int
    height: int
    top_down: bool
    bits_per_pixel: int
    row_stride: int
    palette: list[Rgb] | None
    masks: BitMasks | None


@dataclass(frozen=True)
class EpdPlanes:
    bw_bytes: bytes
    red_bytes: bytes
    red_pixels: int


def read_u16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "little", signed=False)


def read_u32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "little", signed=False)


def read_i32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "little", signed=True)


def read_palette(data: bytes, dib_size: int, bits_per_pixel: int, pixel_offset: int) -> list[Rgb] | None:
    if bits_per_pixel > 8:
        return None

    palette_offset = 14 + dib_size
    max_entries = 1 << bits_per_pixel
    available_entries = max(0, (pixel_offset - palette_offset) // 4)
    entries = min(max_entries, available_entries)
    palette: list[Rgb] = []

    for i in range(entries):
        p = palette_offset + i * 4
        palette.append(Rgb(r=data[p + 2], g=data[p + 1], b=data[p]))

    if not palette:
        raise ValueError(f"BMP bit depth {bits_per_pixel} requires a palette")
    return palette


def read_bit_masks(data: bytes, dib_size: int, bits_per_pixel: int, compression: int, pixel_offset: int) -> BitMasks | None:
    if bits_per_pixel != 16:
        return None

    if compression == 3:
        mask_offset = 14 + 40 if dib_size >= 52 else 14 + dib_size
        if mask_offset + 12 > pixel_offset or mask_offset + 12 > len(data):
            raise ValueError("16-bit BI_BITFIELDS BMP is missing RGB masks")
        return BitMasks(
            r=read_u32(data, mask_offset),
            g=read_u32(data, mask_offset + 4),
            b=read_u32(data, mask_offset + 8),
        )

    # BI_RGB 16-bit BMPs are historically RGB555. If a file uses RGB565 it
    # should normally declare BI_BITFIELDS masks, which this parser supports.
    return BitMasks(r=0x7C00, g=0x03E0, b=0x001F)


def read_bmp(file_path: Path) -> BmpInfo:
    data = file_path.read_bytes()
    if len(data) < 54 or data[0:2] != b"BM":
        raise ValueError("Input is not a BMP file")

    pixel_offset = read_u32(data, 10)
    dib_size = read_u32(data, 14)
    if dib_size < 40:
        raise ValueError(f"Unsupported BMP DIB header size: {dib_size}")

    width = read_i32(data, 18)
    raw_height = read_i32(data, 22)
    height = abs(raw_height)
    top_down = raw_height < 0
    planes = read_u16(data, 26)
    bits_per_pixel = read_u16(data, 28)
    compression = read_u32(data, 30)

    if planes != 1:
        raise ValueError(f"Unsupported BMP plane count: {planes}")
    if width != WIDTH or height != HEIGHT:
        raise ValueError(f"BMP must be {WIDTH}x{HEIGHT}, got {width}x{height}")
    if compression != 0 and not (bits_per_pixel == 16 and compression == 3):
        raise ValueError(f"Only uncompressed BI_RGB BMP is supported, plus 16-bit BI_BITFIELDS, compression={compression}")
    if bits_per_pixel not in {1, 4, 8, 16, 24, 32}:
        raise ValueError(f"Unsupported BMP bit depth: {bits_per_pixel}")

    row_stride = ((bits_per_pixel * width + 31) // 32) * 4
    palette = read_palette(data, dib_size, bits_per_pixel, pixel_offset)
    masks = read_bit_masks(data, dib_size, bits_per_pixel, compression, pixel_offset)
    needed = pixel_offset + row_stride * height
    if len(data) < needed:
        raise ValueError("BMP pixel data is truncated")

    return BmpInfo(
        data=data,
        pixel_offset=pixel_offset,
        width=width,
        height=height,
        top_down=top_down,
        bits_per_pixel=bits_per_pixel,
        row_stride=row_stride,
        palette=palette,
        masks=masks,
    )


def decode_masked_channel(value: int, mask: int) -> int:
    if mask == 0:
        return 0

    shift = 0
    shifted_mask = mask
    while (shifted_mask & 1) == 0:
        shifted_mask >>= 1
        shift += 1

    raw = (value & mask) >> shift
    return round((raw * 255) / shifted_mask)


def get_pixel_rgb(info: BmpInfo, x: int, y: int) -> Rgb:
    file_y = y if info.top_down else info.height - 1 - y
    row = info.pixel_offset + file_y * info.row_stride
    data = info.data

    if info.bits_per_pixel == 24:
        p = row + x * 3
        return Rgb(r=data[p + 2], g=data[p + 1], b=data[p])

    if info.bits_per_pixel == 32:
        p = row + x * 4
        return Rgb(r=data[p + 2], g=data[p + 1], b=data[p])

    if info.bits_per_pixel == 16:
        if info.masks is None:
            raise ValueError("Internal error: 16-bit BMP is missing masks")
        value = read_u16(data, row + x * 2)
        return Rgb(
            r=decode_masked_channel(value, info.masks.r),
            g=decode_masked_channel(value, info.masks.g),
            b=decode_masked_channel(value, info.masks.b),
        )

    if info.palette is None:
        raise ValueError("Internal error: indexed BMP is missing palette")

    if info.bits_per_pixel == 8:
        return info.palette[data[row + x]]

    if info.bits_per_pixel == 4:
        value = data[row + x // 2]
        index = value >> 4 if x % 2 == 0 else value & 0x0F
        return info.palette[index]

    value = data[row + x // 8]
    index = (value >> (7 - (x % 8))) & 1
    return info.palette[index]


def is_red_pixel(rgb: Rgb, red_threshold: int, red_delta: int) -> bool:
    return rgb.r >= red_threshold and rgb.r - rgb.g >= red_delta and rgb.r - rgb.b >= red_delta


class PlaneBuilder:
    def __init__(self) -> None:
        self.out: list[int] = []
        self.bit_buffer = 0
        self.bit_count = 0

    def push(self, bit: int) -> None:
        self.bit_buffer = (self.bit_buffer << 1) | bit
        self.bit_count += 1
        if self.bit_count == 8:
            self.out.append(self.bit_buffer)
            self.bit_buffer = 0
            self.bit_count = 0

    def finish(self) -> bytes:
        if self.bit_count:
            self.out.append(self.bit_buffer << (8 - self.bit_count))
        if len(self.out) != IMAGE_BYTES:
            raise ValueError(f"Internal error: expected {IMAGE_BYTES} image bytes, got {len(self.out)}")
        return bytes(self.out)


def bmp_to_epd_planes(info: BmpInfo, args: argparse.Namespace) -> EpdPlanes:
    bw = PlaneBuilder()
    red = PlaneBuilder()
    red_pixels = 0

    # The debugger and tag payload use column-major data in left-to-right order.
    for x in range(info.width):
        for y in range(info.height):
            rgb = get_pixel_rgb(info, x, y)
            red_bit = 1 if is_red_pixel(rgb, args.red_threshold, args.red_delta) else 0
            if red_bit:
                red_pixels += 1

            luminance = 0.299 * rgb.r + 0.587 * rgb.g + 0.114 * rgb.b
            white_bit = 1 if not red_bit and luminance >= args.threshold else 0
            bw.push(white_bit)
            red.push(red_bit)

    return EpdPlanes(bw_bytes=bw.finish(), red_bytes=red.finish(), red_pixels=red_pixels)


def append_image_data_packets(packets: list[bytes], prepare_command: int, image_bytes: bytes) -> None:
    packets.append(bytes([prepare_command]))
    for i in range(0, len(image_bytes), BLE_PAYLOAD_BYTES):
        packets.append(bytes([0x02]) + image_bytes[i : i + BLE_PAYLOAD_BYTES])


def build_ble_packets(planes: EpdPlanes, mode: str) -> list[bytes]:
    packets = [bytes([0x01, 0xFF])]

    if mode == "bwr":
        packets.append(bytes([0x00, 0x02]))
        append_image_data_packets(packets, 0x04, planes.bw_bytes)
        append_image_data_packets(packets, 0x05, planes.red_bytes)
    else:
        packets.append(bytes([0x00, 0x01]))
        append_image_data_packets(packets, 0x04, planes.bw_bytes)

    packets.append(bytes([0x03]))
    return packets


def write_output(file_path: Path, packets: list[bytes], records: bool) -> int:
    if records:
        output = b"".join(len(packet).to_bytes(2, "little") + packet for packet in packets)
    else:
        output = b"".join(packets)
    file_path.write_bytes(output)
    return len(output)


def bounded_byte(value: str) -> int:
    number = int(value, 10)
    if number < 0 or number > 255:
        raise argparse.ArgumentTypeError("must be a number from 0 to 255")
    return number


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert a 212x104 BMP to raw Hanshow BLE payload bytes.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Default output is raw BLE writes concatenated together:\n"
            "  BW:  01ff, 0001, 04, repeated(02 + up to 200 BW image bytes), 03\n"
            "  BWR: 01ff, 0002, 04, repeated(02 + BW bytes), 05, repeated(02 + red bytes), 03\n\n"
            "--mode=auto switches to BWR if red pixels are detected.\n"
            "--records writes each BLE packet as: uint16_le_length + packet_bytes."
        ),
    )
    parser.add_argument("input", type=Path, help="input 212x104 BMP")
    parser.add_argument("output", type=Path, nargs="?", default=Path("image.bin"), help="output bin path")
    parser.add_argument("--threshold", type=bounded_byte, default=128, help="white threshold, 0-255")
    parser.add_argument("--mode", choices=["auto", "bw", "bwr"], default="auto", help="output mode")
    parser.add_argument("--red-threshold", type=bounded_byte, default=160, help="minimum red channel for red detection")
    parser.add_argument("--red-delta", type=bounded_byte, default=50, help="red must exceed green and blue by this amount")
    parser.add_argument("--records", action="store_true", help="write uint16_le length-prefixed packet records")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    bmp = read_bmp(args.input)
    planes = bmp_to_epd_planes(bmp, args)
    mode = "bwr" if args.mode == "auto" and planes.red_pixels > 0 else args.mode
    packets = build_ble_packets(planes, mode)
    total_bytes = write_output(args.output, packets, args.records)

    print(f"BMP: {args.input}")
    print(f"Output: {args.output}")
    print(f"Format: {'uint16_le length-prefixed records' if args.records else 'raw concatenated BLE writes'}")
    print(f"Mode: {mode.upper()}{' (auto)' if args.mode == 'auto' else ''}")
    print(f"BW payload: {len(planes.bw_bytes)} bytes")
    if mode == "bwr":
        print(f"Red payload: {len(planes.red_bytes)} bytes")
        print(f"Red pixels: {planes.red_pixels}")
    print(f"BLE packets: {len(packets)}")
    print(f"File size: {total_bytes} bytes")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
