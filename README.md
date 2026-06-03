# Hanshow Codex 用量监视器

这个项目用于生成汉朔 2.13 寸黑白红电子价签的蓝牙 payload，把当前 Codex 用量显示到价签上，也可以直接通过本机蓝牙上传到设备。

生成画面尺寸为 212x104：

- 红色进度条和文字：5 小时 Codex 剩余额度
- 黑色进度条和文字：1 周 Codex 剩余额度
- 右侧文字：对应额度窗口的 reset 时间或日期

## 文件说明

- `update_codex_payload.py`：主脚本。获取 Codex 用量，渲染 212x104 图像，生成 `codex_usage.bin`，并可选通过 BLE 上传。
- `MatrixSans-Regular.ttf`：生成画面使用的字体。
- `bin_debugger.html`：浏览器调试器，可打开 `*.bin`、查看每一步包、预览画面，也可以用 Web Bluetooth 写入设备。
- `serialize.py`：把 212x104 BMP 转成汉朔价签 BLE payload。
- `example/`：示例输出文件。

## 依赖安装

使用本项目之前，蓝牙电子价签需要先刷入 [`ihopenot/ihopebleepd`](https://github.com/ihopenot/ihopebleepd.git) 固件。该固件提供项目所需的 BLE UART 服务和电子纸写入协议。

```powershell
python -m pip install pillow bleak
```

其中：

- `pillow` 用于渲染 BMP 预览和生成图像。
- `bleak` 用于 Python 通过本机蓝牙上传 payload。

主脚本默认从本机 Codex home 读取登录态 token：

```text
%USERPROFILE%\.codex\auth.json
```

并请求：

```text
https://chatgpt.com/backend-api/wham/usage
```

注意：API 返回的是已用百分比，脚本显示的是剩余百分比，也就是 `100 - used_percent`。

## 生成 Codex 用量 Payload

在项目目录下运行：

```powershell
python update_codex_payload.py --output codex_usage.bin --preview codex_usage.bmp
```

会生成：

- `codex_usage.bin`：真正上传给电子价签的 BLE payload。
- `codex_usage.bmp`：本地预览图。

生成示例值：

```powershell
python update_codex_payload.py --demo --output codex_usage.bin --preview codex_usage.bmp
```

颜色模式：

```powershell
python update_codex_payload.py --color-mode bwr
python update_codex_payload.py --color-mode bw
```

`bwr` 是默认模式，5 小时额度会用红色显示，并输出黑白红 payload。`bw` 会把全部内容渲染成黑白，并输出不包含红色平面的黑白 payload。

默认文字使用普通字重。如果需要加粗上下两行文字：

```powershell
python update_codex_payload.py --bold
```

默认 payload 会先发送清屏为全白命令。如果不想在写入前清屏：

```powershell
python update_codex_payload.py --no-clear
```

手动指定数值：

```powershell
python update_codex_payload.py --five-hour-percent 99 --five-hour-reset 19:06 --week-percent 92 --week-reset "Jun 08"
```

也可以从 JSON 读取：

```powershell
python update_codex_payload.py --usage-json usage.json
```

示例 JSON：

```json
{
  "5h": { "percent": 99, "reset": "19:06" },
  "1wk": { "percent": 92, "reset": "Jun 08" }
}
```

## 通过蓝牙上传

生成并直接上传：

```powershell
python update_codex_payload.py --upload
```

脚本会按广播设备名扫描，然后连接 UART 服务：

- 设备名：`Ihopeseral_uarttrans` 或 `SPP BLE Server`
- Service UUID：`f000fff0-0451-4000-b000-000000000000`
- Characteristic UUID：`f000fff1-0451-4000-b000-000000000000`

上传时，每个包都会使用 write with response。除最后一个显示刷新命令外，其余包都会等待设备 notification ACK。

脚本会把上一次成功上传到设备的显示状态保存到 `.last_upload_state.json`。如果本次获取到的 5 小时/1 周百分比、reset 文本以及显示选项没有变化，`--upload` 会跳过蓝牙写入。

常用选项：

```powershell
python update_codex_payload.py --upload --ble-scan-timeout 60000
python update_codex_payload.py --upload --ble-name "SPP BLE Server"
python update_codex_payload.py --upload --force-update
```

`--force-update` 会忽略上次上传状态，强制每次运行都写入设备。

## 调试 Bin 文件

用支持 Web Bluetooth 的浏览器打开项目根目录里的 `bin_debugger.html`。

例如在项目目录下运行：

```powershell
start .\bin_debugger.html
```

调试器可以：

- 打开 `codex_usage.bin` 或 `image.bin`
- 查看每个 BLE 包的时间线
- 逐步预览清屏、初始化、黑白数据、红色数据、刷新显示
- 在浏览器里连接 BLE 设备
- 把当前 bin 写入价签

## 从 BMP 生成 Payload

`serialize.py` 可以把 212x104 BMP 转成相同格式的 BLE payload：

```powershell
python serialize.py input.bmp image.bin
```

常用选项：

```powershell
python serialize.py input.bmp image.bin --mode=auto
python serialize.py input.bmp image.bin --mode=bwr --threshold=128 --red-threshold=160 --red-delta=50
python serialize.py input.bmp image.bin --records
```

支持 1/4/8/16/24/32 位未压缩 BMP。红色像素会写入红色平面，同时对应位置不会再写入黑白平面。

## Payload 格式

默认输出是把每个 BLE 写入包直接拼接在一起：

```text
01 ff        清屏为全白
00 02        初始化黑白红模式
04           准备黑白 RAM
02 ...       黑白图像数据，每包最多 200 字节 payload
05           准备红色 RAM
02 ...       红色图像数据，每包最多 200 字节 payload
03           刷新显示
```

图像数据是 212x104 的按列打包 bit 数据。

## 注意事项

- `MatrixSans-Regular.ttf` 放在项目根目录时，生成画面会优先使用它。
- `codex_usage.bmp` 只是预览图，真正上传给价签的是 `codex_usage.bin`。
- 如果 Python 蓝牙扫描找不到设备，可以先用 `bin_debugger.html` 验证设备是否正在广播、是否能被浏览器连接。
- 如果最后刷新显示后设备没有再返回 ACK，这是正常情况，脚本不会等待最后一个包的返回。
