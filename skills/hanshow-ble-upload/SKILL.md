---
name: hanshow-ble-upload
description: 用 update_codex_payload.py --upload 通过本机蓝牙把 Codex 用量 payload 写入汉朔电子价签（ihopebleepd 固件），并处理上传缓存的跳过逻辑（.last_upload_state.json、--skip-full-cache、--force-update）以及 BLE 设备名、超时和 ACK 问题。Triggers: --upload, BLE upload, 蓝牙上传, 刷新价签, bleak, Ihopeseral_uarttrans, SPP BLE Server, Target BLE device not found, ACK timeout, skipping upload.
---

# 通过蓝牙上传

前提：价签已刷入 [ihopenot/ihopebleepd](https://github.com/ihopenot/ihopebleepd.git) 固件，并且已经装好依赖 `python -m pip install -r requirements.txt`（需要其中的 bleak）。

生成并上传：

```powershell
python update_codex_payload.py --upload
```

数据来源和显示选项（`--demo`、`--color-mode`、`--bold` 等）与 `hanshow-codex-payload` skill 中的相同，可以和 `--upload` 一起用。

## 协议

- 按广播名扫描设备，然后连接 service `f000fff0-0451-4000-b000-000000000000` / characteristic `f000fff1-0451-4000-b000-000000000000`。
- 每个包都用 write-with-response 写入，并等待 notification ACK；最后一个刷新命令（`03`）不等 ACK，这是正常的。
- 默认只匹配设备名 `Ihopeseral_uarttrans`。传了 `--ble-name` 就**只**使用指定的名称（可以重复传多个），例如 `--ble-name "SPP BLE Server"`。

## 跳过逻辑（upload 输出 "skipping upload" 不算失败）

- 每次上传成功后，状态会保存到 `.last_upload_state.json`（可以用 `--upload-state-file` 改路径）。如果两次的百分比、reset 文本和显示选项都没变，就跳过蓝牙写入。
- `--skip-full-cache`：上次和这次的 5h 都是 100%，且 1wk 状态没变时也跳过，哪怕 5h 的 reset 文本变了。
- `--force-update`：忽略缓存，强制写入。

## 常用参数

```powershell
python update_codex_payload.py --upload --ble-scan-timeout 60000
python update_codex_payload.py --upload --ble-ack-timeout 20000
python update_codex_payload.py --upload --ble-name "SPP BLE Server"
python update_codex_payload.py --upload --skip-full-cache
python update_codex_payload.py --upload --force-update
```

超时单位是毫秒，默认扫描 30000、ACK 10000。

## 排查

- 报 `Target BLE device not found. Saw: ...`：看输出里实际扫到了哪些名字，再用 `--ble-name` 指定正确的名称，或者加长 `--ble-scan-timeout`。
- Python 扫不到时，先用 `bin_debugger.html` 确认设备确实在广播、浏览器能连上（见 `hanshow-bin-debug` skill），以此区分是设备问题还是本机蓝牙栈问题。
- ACK 超时：设备可能断开了，或者固件不对（必须是 ihopebleepd）。
- 这个脚本只能上传它自己渲染的画面。要上传 `serialize.py` 生成的任意 bin，请用 `bin_debugger.html`。
