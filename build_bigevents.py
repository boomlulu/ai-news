#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_bigevents.py — 生成「大事件」长期记忆（月度 + 年度），由日报自动归并。

模型（对应需求）：
  · 最近两个月：每个月一个 archive/大事件/YYYY-MM.md，把当月每天的「头条」汇总为当月大事件。
  · 超过最近两个月的月份：归并进 archive/大事件/YYYY.md（年度最终档案，按年保存、长期保留）。
  · 以「最新一期日报的日期」为锚点来界定「最近两个月」窗口。

数据来源：archive/AI每日精选_YYYY-MM-DD.md（每期日报的纯文本摘要，取其中 #1 头条）。
渲染：大事件页 index.html 的 JS 解析这些 md（## 日期 ｜ 分类 ｜ 标题 + 正文行）。

特性：
  · 幂等 / 未来式：每次都从日报源「全量重算」月度与年度档案，反复运行结果一致；
    新的一天、新的月份无需改脚本。一个月滚出两月窗口后，会自动从月度转入年度。
  · 顺带把大事件页抽屉里的「日报」两个快捷链接刷新为最近两天。

用法：python3 build_bigevents.py      （建议每天生成完日报后跑一次）
"""
import os
import re
import sys
import glob

ROOT = os.environ.get("AINEWS_DIR") or os.path.dirname(os.path.realpath(__file__))
ARCHIVE = os.path.join(ROOT, "archive")
BIG = os.path.join(ARCHIVE, "大事件")
WINDOW = 2  # 最近 N 个日历月作为「月度」，更早的滚入「年度」

# 把日报分类的首词映射到大事件页能着色的类目（其余保留首词，默认黑色）
CAT_KNOWN = {"政策", "监管", "安全", "研究", "论文", "模型", "开源", "产品", "商业", "落地", "平台"}


def parse_daily(path):
    """从一期日报摘要里抽出 #1 头条：标题 / 分类 / 影响指数 / 为什么重要 / 来源。"""
    base = os.path.basename(path)
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", base)
    if not m:
        return None
    y, mo, da = int(m.group(1)), int(m.group(2)), int(m.group(3))
    text = open(path, encoding="utf-8").read().replace("\r", "")

    h = re.search(r"^###\s+(.+)$", text, re.M)            # 第一个 ### = 头条
    if not h:
        return None
    title = re.sub(r"^\d+\s*[.、．]\s*", "", h.group(1).strip()).strip()

    # 头条小节：从该 ### 到下一个 ###/## 之间
    start = h.end()
    nxt = re.search(r"^(###|##)\s", text[start:], re.M)
    block = text[start: start + nxt.start()] if nxt else text[start:]

    def grab(pat):
        mm = re.search(pat, block)
        return mm.group(1).strip() if mm else ""

    cat = grab(r"\*\*分类\*\*[：:]\s*([^｜|\n]+)")
    impact = grab(r"\*\*影响指数\*\*[：:]\s*([0-9.]+)")
    why = grab(r"\*\*为什么(?:重要|是爆点)\*\*[：:]\s*([^\n]+)")
    src = grab(r"\*\*来源\*\*[：:]\s*([^\n]+)")

    cat_kw = re.split(r"[·・/\s]", cat)[0] if cat else ""
    return {
        "y": y, "m": mo, "d": da, "ym": "%04d-%02d" % (y, mo),
        "idx": y * 12 + mo, "title": title,
        "cat": cat_kw, "impact": float(impact) if impact else 0.0,
        "why": why, "src": src,
    }


def event_md(date_label, ev):
    """一条事件 → 大事件页认识的 markdown 块。"""
    cat = ev["cat"] if ev["cat"] in CAT_KNOWN else (ev["cat"] or "")
    out = ["## %s ｜ %s ｜ %s" % (date_label, cat, ev["title"])]
    if ev["why"]:
        out.append("为什么重要：" + ev["why"])
    if ev["src"]:
        out.append("来源：" + ev["src"])
    return "\n".join(out)


def write_if_changed(path, content):
    old = open(path, encoding="utf-8").read() if os.path.exists(path) else None
    if old == content:
        return False
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return True


def refresh_drawer_daily_links(latest_dates):
    """把大事件页抽屉「日报」分组的两个链接刷新为最近两天（幂等）。"""
    idx = os.path.join(BIG, "index.html")
    if not os.path.exists(idx) or not latest_dates:
        return False
    html = open(idx, encoding="utf-8").read()
    links = "".join(
        '\n        <a href="../%s.html" aria-label="查看 %s 日报">%s</a>' % (d, d, d[5:])
        for d in latest_dates
    )
    new_block = '<span class="grp">日报</span>%s\n        <span class="grp">归档</span>' % links
    new_html = re.sub(
        r'<span class="grp">日报</span>.*?<span class="grp">归档</span>',
        lambda _: new_block, html, count=1, flags=re.S,
    )
    return write_if_changed(idx, new_html) if new_html != html else False


def main():
    if not os.path.isdir(BIG):
        print("✗ 找不到大事件目录：%s" % BIG)
        return 1

    files = sorted(glob.glob(os.path.join(ARCHIVE, "AI每日精选_20[0-9][0-9]-[0-1][0-9]-[0-3][0-9].md")))
    evs = [e for e in (parse_daily(f) for f in files) if e]
    if not evs:
        print("没有找到日报摘要（AI每日精选_*.md），无事可做。")
        return 0

    latest_idx = max(e["idx"] for e in evs)
    window_min = latest_idx - (WINDOW - 1)            # 窗口内：idx >= window_min
    latest_year = max(e["y"] for e in evs)
    latest_ym = max(e["ym"] for e in evs)
    latest_dates = sorted({"%04d-%02d-%02d" % (e["y"], e["m"], e["d"]) for e in evs})[-2:]

    # 按月分组
    by_month = {}
    for e in evs:
        by_month.setdefault(e["ym"], []).append(e)

    print("站点根：%s" % ROOT)
    print("锚点（最新一期）：%s · 月度窗口=最近 %d 个月" % (latest_ym, WINDOW))
    print("-" * 56)

    changed = 0

    # ---- 月度文件：每个有数据的月份都写（页面只取最近两个月）----
    for ym, items in sorted(by_month.items()):
        items.sort(key=lambda e: (e["d"]), reverse=True)   # 当月内：新日在上
        y, mo = int(ym[:4]), int(ym[5:7])
        head = "# %d 年 %d 月 · AI 大事件\n> 当月每日头条汇总（来自日报，自动归并；最近两个月在此按月展示，更早归入年度档案）。\n" % (y, mo)
        body = "\n\n".join(event_md("%d月%d日" % (mo, e["d"]), e) for e in items)
        if write_if_changed(os.path.join(BIG, ym + ".md"), head + "\n" + body + "\n"):
            print("✓ 月度 %s.md（%d 条）" % (ym, len(items)))
            changed += 1

    # ---- 年度文件：滚出窗口的月份，每月取影响指数最高的一条 ----
    aged = {}  # year -> list of (month, top_event)
    for ym, items in by_month.items():
        idx = int(ym[:4]) * 12 + int(ym[5:7])
        if idx < window_min:                           # 已超出最近两个月
            top = max(items, key=lambda e: (e["impact"], e["d"]))
            aged.setdefault(int(ym[:4]), []).append((int(ym[5:7]), top))

    years_to_write = set(aged.keys()) | {latest_year}   # 当前年至少要有文件（含说明）
    for y in sorted(years_to_write):
        head = "# %d · AI 年度大事件\n> 超过最近两个月的月份在此归并保存（每年一档，长期保留）。\n" % y
        months = sorted(aged.get(y, []), key=lambda t: t[0], reverse=True)
        if months:
            body = "\n\n".join(event_md("%d月" % mo, ev) for mo, ev in months)
            content = head + "\n" + body + "\n"
        else:
            content = head + "> 暂无归并条目（当前所有月份仍在最近两个月窗口内）。\n"
        if write_if_changed(os.path.join(BIG, "%d.md" % y), content):
            print("✓ 年度 %d.md（归并 %d 个月）" % (y, len(months)))
            changed += 1

    if refresh_drawer_daily_links(latest_dates):
        print("✓ 刷新大事件页抽屉「日报」链接 → %s" % " / ".join(latest_dates))
        changed += 1

    print("-" * 56)
    print("完成：写入/更新 %d 个文件（无变化的已跳过）。" % changed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
