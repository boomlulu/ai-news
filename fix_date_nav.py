#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_date_nav.py — 维护历史新闻页的「日期导航」，让旧新闻能往回走到新新闻。

背景：每期归档页 archive/YYYY-MM-DD.html 的日期抽屉只有一个「向后看」的三天窗口
      （前两天 / 前一天 / 本期），没有「次日」或「最新」入口。结果是：打开一篇旧新闻后
      只能越翻越旧，回不到最近的新闻。

本脚本对每个归档页的抽屉做两件事：
  A) 补一个「较新」分组：次日 → 紧邻的下一期归档页（存在才加）；最新 → ../index.html（一键回到最新）
  B) 把激活项（当期）的文字「今天」改成它自己的日期（如 6/15）；只有最新一期才显示「今天」。
     —— 以最新日期为锚点：今天生成新一期后，昨天那页的「今天」会自动翻成它的日期。

特性：
  · 幂等：用 <!--navfix:start/end--> 标记包裹注入内容，每次运行先清除旧标记再重写，
          反复运行结果一致；最新一期明天有了次日页后，重跑会自动补上「次日」。
  · 未来式：自动扫描 archive 下所有 YYYY-MM-DD.html，新日期无需改脚本。
  · 安全：只在抽屉（date-menu）里、紧靠「三月」分组前插入，不动其它结构/CSS/JS。

用法：
  python3 fix_date_nav.py            # 维护所有归档页（建议每天生成新闻后跑一次）
  AINEWS_DIR=/path/to/AINews python3 fix_date_nav.py   # 指定站点根
"""
import os
import re
import sys
import glob

ROOT = os.environ.get("AINEWS_DIR") or os.path.dirname(os.path.realpath(__file__))
ARCHIVE = os.path.join(ROOT, "archive")

START = "<!--navfix:start-->"
END = "<!--navfix:end-->"
# 紧靠这个分组标签之前插入；它只出现在抽屉里
ANCHOR = '<span class="grp">三月</span>'
DATE_RE = re.compile(r"^20\d\d-[01]\d-[0-3]\d$")


def build_block(dates, idx):
    """为第 idx 期生成「较新」导航块（次日可选 + 最新）。"""
    parts = [START, '<span class="grp">较新</span>']
    if idx < len(dates) - 1:                       # 存在更新的一期 → 加「次日」
        nxt = dates[idx + 1]
        parts.append(
            '<a href="%s.html" aria-label="查看次日 %s 新闻">次日</a>' % (nxt, nxt)
        )
    parts.append('<a href="../index.html" aria-label="回到最新一期">最新</a>')
    parts.append(END)
    return "".join(parts)


def md_label(d):
    """'2026-06-15' -> '6/15'（与抽屉里相邻日期同款 M/D 格式）。"""
    _, m, day = d.split("-")
    return "%d/%d" % (int(m), int(day))


# 抽屉里「当期」激活链接：<a class="active" href=... aria-current="page" aria-label=...>今天</a>
ACTIVE_RE = re.compile(
    r'(<a class="active"\s+href="[^"]*"\s+aria-current="page"\s+aria-label="[^"]*">)[^<]*(</a>)'
)


def main():
    if not os.path.isdir(ARCHIVE):
        print("✗ 找不到归档目录：%s" % ARCHIVE)
        return 1

    files = sorted(glob.glob(os.path.join(ARCHIVE, "20[0-9][0-9]-[0-1][0-9]-[0-3][0-9].html")))
    dates = [os.path.basename(f)[:-5] for f in files]
    dates = [d for d in dates if DATE_RE.match(d)]
    dates.sort()
    if not dates:
        print("没有找到任何 archive/YYYY-MM-DD.html，无事可做。")
        return 0

    print("站点根：%s" % ROOT)
    print("归档页：%d 期（%s … %s）" % (len(dates), dates[0], dates[-1]))
    print("-" * 56)

    changed = skipped = warned = 0
    for idx, d in enumerate(dates):
        path = os.path.join(ARCHIVE, d + ".html")
        with open(path, encoding="utf-8") as f:
            html = f.read()
        orig = html

        # 1) 先清除已有的注入块（幂等 / 可更新次日目标）
        html = re.sub(re.escape(START) + r".*?" + re.escape(END), "", html, flags=re.S)

        # A) 在「三月」分组前插入「较新」块
        block = build_block(dates, idx)
        if ANCHOR in html:
            html = html.replace(ANCHOR, block + ANCHOR, 1)
        else:
            print("⚠  %s 未找到抽屉锚点，跳过" % (d + ".html"))
            warned += 1
            continue

        # B) 激活项文字：最新一期=今天，其余=自身日期
        is_latest = (idx == len(dates) - 1)
        label = "今天" if is_latest else md_label(d)
        new_html, n = ACTIVE_RE.subn(lambda mm: mm.group(1) + label + mm.group(2), html, count=1)
        if n:
            html = new_html
        else:
            print("⚠  %s 未找到激活链接，仅补了较新分组" % (d + ".html"))
            warned += 1

        if html != orig:
            with open(path, "w", encoding="utf-8") as f:
                f.write(html)
            nav = "次日+最新" if not is_latest else "最新（暂无次日，明日自动补）"
            print("✓  %s  →  当期标签「%s」· %s" % (d + ".html", label, nav))
            changed += 1
        else:
            print("⏭  %s  导航已最新，跳过" % (d + ".html"))
            skipped += 1

    print("-" * 56)
    print("汇总：共 %d 期 · 更新 %d · 跳过 %d · 警告 %d" % (len(dates), changed, skipped, warned))
    return 1 if warned else 0


if __name__ == "__main__":
    sys.exit(main())
