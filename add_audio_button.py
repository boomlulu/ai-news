#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
add_audio_button.py — 给每期日报页加一个「语音播报」按钮（取站点上的 mp3 播放）。

行为（对应需求）：
  · 每页右下角一个悬浮按钮，指向本期的 tts/samples/daily-ai-news-<日期>-broadcast.mp3。
  · 页面加载时探测该 mp3 是否存在（<audio preload=metadata>）：
        存在 → 按钮可点，点击播放 / 暂停；
        不存在（如还没生成/还没推上线）→ 按钮显示「🔇 播报未生成」并禁用。
  · 首页 index.html 指向最新一期；归档页指向各自日期（用 ../ 回到站点根的 tts/samples）。

特性：幂等 / 未来式——用 <!--aiaudio--> 标记包裹，每次先清除再注入；首页的日期每天变化也会自动更新。
注入位置：</body> 前（与封面版式无关，所有历史模板都适用）。

用法：python3 add_audio_button.py   （建议每天生成日报后、与 fix_date_nav.py 一起跑）
"""
import os
import re
import sys
import glob

ROOT = os.environ.get("AINEWS_DIR") or os.path.dirname(os.path.realpath(__file__))
ARCHIVE = os.path.join(ROOT, "archive")
START, END = "<!--aiaudio:start-->", "<!--aiaudio:end-->"

BLOCK = START + """
<style>
#aiAudioFab{position:fixed;z-index:40;right:12px;bottom:calc(16px + env(safe-area-inset-bottom,0px));display:inline-flex;align-items:center;gap:8px;min-height:42px;padding:9px 15px;border:1px solid var(--ink,#111);border-radius:999px;background:var(--ink,#111);color:var(--paper,#fbf8ef);font-family:ui-sans-serif,system-ui,-apple-system,"PingFang SC",sans-serif;font-size:13px;font-weight:900;letter-spacing:.03em;cursor:pointer;box-shadow:0 10px 24px rgba(38,31,20,.22);-webkit-tap-highlight-color:transparent}
#aiAudioFab[disabled]{opacity:.55;cursor:default;background:rgba(251,248,239,.92);color:var(--muted,#69645b);border-style:dashed;box-shadow:0 6px 16px rgba(38,31,20,.12)}
#aiAudioFab.playing{background:var(--red,#b52823);border-color:var(--red,#b52823);color:#fff}
@media (max-width:390px){#aiAudioFab{font-size:12px;padding:8px 13px}}
</style>
<button type="button" id="aiAudioFab" disabled aria-label="收听本期 AI 播报">⏳ 检查中…</button>
<audio id="aiAudioEl" preload="none" src="__MP3__"></audio>
<script>
(function(){
  var b=document.getElementById('aiAudioFab'),a=document.getElementById('aiAudioEl');
  if(!b||!a)return;
  var IDLE='\\uD83D\\uDD0A 收听播报',PLAY='\\u23F8 暂停',MISS='\\uD83D\\uDD07 播报未生成';
  // 用 HEAD 探测站点上是否有该 mp3（比移动端不稳定的 audio 预加载更可靠）
  fetch(a.getAttribute('src'),{method:'HEAD'}).then(function(r){
    if(r.ok){b.disabled=false;b.textContent=IDLE;}
    else{b.disabled=true;b.textContent=MISS;}
  }).catch(function(){b.disabled=false;b.textContent=IDLE;}); // 网络异常仍允许点按尝试
  a.addEventListener('play',function(){b.classList.add('playing');b.textContent=PLAY;});
  a.addEventListener('pause',function(){b.classList.remove('playing');if(!b.disabled)b.textContent=IDLE;});
  a.addEventListener('ended',function(){b.classList.remove('playing');b.textContent=IDLE;});
  a.addEventListener('error',function(){b.disabled=true;b.classList.remove('playing');b.textContent=MISS;});
  b.addEventListener('click',function(){if(b.disabled)return;if(a.paused){a.play().catch(function(){b.disabled=true;b.textContent=MISS;});}else{a.pause();}});
})();
</script>
""" + END + "\n"


def inject(path, mp3_url):
    if not os.path.exists(path):
        return None
    html = open(path, encoding="utf-8").read()
    html = re.sub(re.escape(START) + r".*?" + re.escape(END) + r"\s*", "", html, flags=re.S)
    if "</body>" not in html:
        return False
    block = BLOCK.replace("__MP3__", mp3_url)
    html = html.replace("</body>", block + "</body>", 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return True


def main():
    files = sorted(glob.glob(os.path.join(ARCHIVE, "20[0-9][0-9]-[0-1][0-9]-[0-3][0-9].html")))
    dates = [os.path.basename(f)[:-5] for f in files]
    if not dates:
        print("没有找到归档日报页。")
        return 0
    latest = max(dates)

    targets = [(os.path.join(ROOT, "index.html"),
                "tts/samples/daily-ai-news-%s-broadcast.mp3" % latest)]
    for d in dates:
        targets.append((os.path.join(ARCHIVE, d + ".html"),
                        "../tts/samples/daily-ai-news-%s-broadcast.mp3" % d))

    print("站点根：%s ｜ 首页指向最新一期 %s" % (ROOT, latest))
    print("-" * 56)
    ok = miss = 0
    for path, url in targets:
        r = inject(path, url)
        name = os.path.relpath(path, ROOT)
        if r is True:
            print("✓ %s  →  %s" % (name, url))
            ok += 1
        elif r is False:
            print("⚠ %s 缺 </body>，跳过" % name)
            miss += 1
        else:
            print("⚠ %s 不存在，跳过" % name)
            miss += 1
    print("-" * 56)
    print("完成：注入/更新 %d 页，跳过 %d 页。" % (ok, miss))
    return 0


if __name__ == "__main__":
    sys.exit(main())
