const vscode = require('vscode');
const { spawn } = require('child_process');
const path = require('path');

const AFPLAY = '/usr/bin/afplay';
let current = null; // 当前 afplay 子进程

function stopCurrent() {
  if (current && !current.killed) {
    try { current.kill('SIGTERM'); } catch (e) { /* ignore */ }
  }
  current = null;
}

function activate(context) {
  const play = vscode.commands.registerCommand('ainewsAudio.play', (uri) => {
    const target = uri || (vscode.window.activeTextEditor && vscode.window.activeTextEditor.document.uri);
    if (!target || target.scheme !== 'file') {
      vscode.window.showWarningMessage('没有可播放的本地音频文件');
      return;
    }
    const filePath = target.fsPath;
    stopCurrent();
    const child = spawn(AFPLAY, [filePath], { stdio: 'ignore' });
    current = child;
    const name = path.basename(filePath);
    vscode.window.setStatusBarMessage(`▶ 正在播放 ${name}`, 5000);
    child.on('error', (err) => {
      vscode.window.showErrorMessage(`播放失败: ${err.message}`);
      if (current === child) current = null;
    });
    child.on('exit', () => {
      if (current === child) current = null;
    });
  });

  const stop = vscode.commands.registerCommand('ainewsAudio.stop', () => {
    stopCurrent();
    vscode.window.setStatusBarMessage('⏹ 已停止播放', 2000);
  });

  context.subscriptions.push(play, stop, { dispose: stopCurrent });
}

function deactivate() {
  stopCurrent();
}

module.exports = { activate, deactivate };
