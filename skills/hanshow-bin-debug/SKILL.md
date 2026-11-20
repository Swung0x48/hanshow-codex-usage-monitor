---
name: hanshow-bin-debug
description: 用 bin_debugger.html 检查、逐包预览汉朔电子价签的 .bin payload，并通过 Web Bluetooth 从浏览器写入价签；也包括 bin 的字节格式、文件大小自查和手工解码位平面。Triggers: bin_debugger.html, 调试 bin, 解析 bin, 预览 bin, payload 格式, Web Bluetooth, codex_usage.bin, image.bin, decode e-paper payload.
---

# 调试 bin 文件

```powershell
start .\bin_debugger.html
```

需要支持 Web Bluetooth 的浏览器（Chrome / Edge）。它可以：

- 打开 `codex_usage.bin`、`image.bin` 等文件；
- 查看每个 BLE 包的时间线，逐步预览清屏、初始化、BW 数据、红色数据和刷新这几步；
- 在浏览器里连接价签，并写入当前 bin。这是上传 `serialize.py` 生成的 bin 的方式。

Python 蓝牙扫描找不到设备时，也可以先用这个页面确认设备在广播、能被连接。

## 快速自查

| 模式 | 带清屏 | 不带清屏 |
|---|---|---|
| BW | 2776 | 2774 |
| BWR | 5547 | 5545 |

文件应以 `01 ff 00 01`（BW）或 `01 ff 00 02`（BWR）开头；不带清屏时则以 `00 01` / `00 02` 开头。参考样例在 `example/` 目录。

需要手工解析或生成 bin 时，读 [payload-format.md](payload-format.md)。
