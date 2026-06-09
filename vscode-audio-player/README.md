# AINews Audio Player

资源管理器右键 `.wav/.mp3/.flac/.ogg/.m4a/.aac` → **▶ 播放音频 / ⏹ 停止播放**。底层调用 macOS `afplay`，同一时刻只播一个（再播会先停上一个）。

## 安装（本地软链，已自动做）
```bash
ln -sfn /Users/boom/Demo/AINews/vscode-audio-player ~/.vscode/extensions/ainews-audio-player-0.0.1
```
装后在 VSCode 里 **Cmd+Shift+P → Developer: Reload Window**（或重启）即生效。

## 用法
- 资源管理器右键音频文件 → ▶ 播放音频 / ⏹ 停止播放
- 命令面板亦可调用 `▶ 播放音频`（播放当前打开文件）/ `⏹ 停止播放`

## 卸载
```bash
rm ~/.vscode/extensions/ainews-audio-player-0.0.1
```
