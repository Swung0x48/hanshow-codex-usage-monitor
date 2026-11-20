---
name: hanshow-codex-payload
description: 用 update_codex_payload.py 把 Codex 5h/1wk 剩余用量渲染成 212x104 画面，生成汉朔电子价签的 codex_usage.bin 和预览 BMP。支持实时 API、演示值、手动值、JSON 和环境变量作为数据来源，也支持 BWR/BW 颜色模式、加粗和不清屏。Triggers: codex_usage.bin, codex_usage.bmp, update_codex_payload.py, Codex 用量, 电子价签画面, e-paper usage display, --demo, --usage-json, --color-mode.
---

# 生成 Codex 用量 payload

在仓库根目录运行（Windows / PowerShell）。依赖：

```powershell
python -m pip install -r requirements.txt
```

基本用法：

```powershell
python update_codex_payload.py --output codex_usage.bin --preview codex_usage.bmp
```

- `codex_usage.bin` 是真正写入价签的数据；`codex_usage.bmp` 只是预览图。改完画面后先看一眼预览图再上传。
- 画面内容：第 1 行和上面的进度条是 5h **剩余**额度（BWR 模式下为红色），第 2 行是 1wk 剩余额度（黑色），右侧是 reset 时间（5h 显示时刻，1wk 显示日期）。
- 字体：项目根目录有 `MatrixSans-Regular.ttf` 时优先用它。
- 要把生成的 bin 写进价签，请用 `hanshow-ble-upload` skill（`--upload`）。

## 用量数据来源

按以下顺序取第一个可用的来源：

1. `--demo`：固定的演示值（5h 50% 14:00，1wk 90% Jun 08）。
2. `--usage-json <JSON 字符串或文件路径>`，或环境变量 `CODEX_USAGE_JSON`：
   ```json
   { "5h": { "percent": 99, "reset": "19:06" }, "1wk": { "percent": 92, "reset": "Jun 08" } }
   ```
3. 命令行手动值：
   ```powershell
   python update_codex_payload.py --five-hour-percent 99 --five-hour-reset 19:06 --week-percent 92 --week-reset "Jun 08"
   ```
4. 环境变量 `CODEX_5H_PERCENT`、`CODEX_5H_RESET`、`CODEX_1WEEK_PERCENT`、`CODEX_1WEEK_RESET`。
5. 默认：请求 `https://chatgpt.com/backend-api/wham/usage`。token 依次取 `--api-token`、`CODEX_USAGE_TOKEN`、`%USERPROFILE%\.codex\auth.json`（可以用 `--codex-home` 改目录）。

手动值、JSON 和环境变量里的百分比会**原样显示为剩余额度**。只有 API 来源会做换算：API 返回的是已用比例，脚本显示 `100 - used_percent`。

不要把 `auth.json` 里的 token 打印出来，也不要写进任何文件。

## 显示选项

| 选项 | 效果 |
|---|---|
| `--color-mode bwr`（默认） | 5h 用红色，输出带红色平面的 BWR payload |
| `--color-mode bw` | 全部黑白，payload 不含红色平面，体积约为一半 |
| `--bold` | 两行文字加粗 |
| `--no-clear` | 不在开头加清屏（`01 ff`）命令 |
