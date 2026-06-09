# AINews Audio Player

资源管理器右键 `.wav/.mp3/.flac/.ogg/.m4a/.aac` → **▶ 播放音频 / ⏹ 停止播放**。底层调用 macOS `afplay`，同一时刻只播一个（再播会先停上一个）。

## 安装（本地软链）

> 装到你实际在用的编辑器的扩展目录。本机用的是 **VSCode Insiders**。

```bash
# VSCode Insiders（本机默认）
ln -sfn /Users/boom/Demo/AINews/vscode-audio-player ~/.vscode-insiders/extensions/ainews-audio-player-0.0.1

# 普通 VSCode stable（仅当改用 stable 才需要）
ln -sfn /Users/boom/Demo/AINews/vscode-audio-player ~/.vscode/extensions/ainews-audio-player-0.0.1
```

装后 **Cmd+Shift+P → Developer: Reload Window**（或重启编辑器）即生效。

## 用法
- 资源管理器右键音频文件 → ▶ 播放音频 / ⏹ 停止播放（在右键菜单**底部**独立一栏）
- 命令面板亦可调用 `▶ 播放音频`（播放当前打开文件）/ `⏹ 停止播放`

## 卸载
```bash
rm ~/.vscode-insiders/extensions/ainews-audio-player-0.0.1
rm ~/.vscode/extensions/ainews-audio-player-0.0.1   # 若装过 stable
```
