---
name: hanshow-bmp-to-bin
description: 用 serialize.py 把 212x104 BMP 转成汉朔电子价签的 BLE payload（image.bin），支持 auto/bw/bwr 模式、亮度和红色阈值、length-prefixed records 格式；也包括用 Pillow 把 PNG/JPG 或其他尺寸的图片预处理成 212x104 BMP。Triggers: serialize.py, BMP 转 bin, 图片转价签, image.bin, convert image to e-paper, --threshold, --red-threshold, --records.
---

# 把图片转成 payload

`serialize.py` 只依赖 Python 标准库，只接受 **恰好 212x104** 的未压缩 BMP（1/4/8/16/24/32 位；16 位还支持 BI_BITFIELDS）。

```powershell
python serialize.py input.bmp image.bin
python serialize.py input.bmp image.bin --mode=auto
python serialize.py input.bmp image.bin --mode=bwr --threshold=128 --red-threshold=160 --red-delta=50
python serialize.py input.bmp image.bin --records
```

- `--mode auto`（默认）：图中有红色像素就输出 BWR，否则输出 BW。`bw` / `bwr` 强制指定模式。
- 红色像素的判定：R ≥ `--red-threshold`，并且 R−G、R−B 都 ≥ `--red-delta`。红色像素只写入红色平面，不写入黑白平面。
- 其余像素按亮度 ≥ `--threshold` 判为白，否则为黑。
- `--records`：每个包前面加 uint16 小端长度前缀。默认是直接拼接。
- `serialize.py` 输出的 bin 开头**一定**带清屏命令，没有 `--no-clear` 选项。

## 预处理非 BMP 或尺寸不对的图片

需要 Pillow。下面的写法会等比缩放并居中，留白处填白色：

```powershell
python -c "from PIL import Image, ImageOps; im = Image.open('input.png').convert('RGB'); ImageOps.pad(im, (212, 104), color='white').save('input.bmp')"
```

如果想铺满画面、裁掉多余部分，把 `ImageOps.pad` 换成 `ImageOps.fit`。图里只能用纯黑、纯白、纯红三种颜色，照片这类连续色调的图会被硬阈值二值化，效果差的话可以先在 Pillow 里抖动处理，或调整 `--threshold`。

## 之后

`serialize.py` 本身不能上传。要检查生成的 bin，或者把它写入价签，请用 `bin_debugger.html`（见 `hanshow-bin-debug` skill）。
