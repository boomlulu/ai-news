"""Generate a TTS-ready Chinese broadcast script (纯文本播报稿) from the daily
AI-news newspaper HTML (or a JSON fields file).

Bridge between the existing newspaper pipeline and TTS:
    filled HTML  ->  daily-ai-news-YYYY-MM-DD-script.txt

Output is plain text fit for Chinese TTS: NO tags / CSS / URLs / {{placeholders}}.
Scales to however many <section id="story-N"> the HTML contains.
"""
from __future__ import annotations
import argparse
import html
import json
import os
import re
import sys

_CN_NUM = "零一二三四五六七八九十"


def cn_ordinal(n: int) -> str:
    if 1 <= n <= 10:
        return _CN_NUM[n]
    if 11 <= n <= 99:
        t, o = divmod(n, 10)
        return ("" if t == 1 else _CN_NUM[t]) + "十" + ("" if o == 0 else _CN_NUM[o])
    return str(n)


def _clean(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"(?is)<script.*?</script>", " ", s)
    s = re.sub(r"(?is)<style.*?</style>", " ", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)          # strip tags
    s = html.unescape(s)
    s = re.sub(r"https?://\S+", "", s)           # drop URLs
    s = re.sub(r"www\.\S+", "", s)
    s = s.replace("·", "，")                 # middot -> ，(better for TTS)
    s = re.sub(r"([A-Za-z0-9\)\]])\s*\^\s*([0-9][0-9.]*)", r"\1的\2次方", s)  # superscript: n^1.014 -> n的1.014次方
    s = s.replace("^", "")                    # drop any stray caret
    s = re.sub(r"[ \t\r\n]+", " ", s).strip()
    s = re.sub(r"\s+([，。、！？：；）】」』])", r"\1", s)      # drop space BEFORE CJK closing punct
    s = re.sub(r"([（【「『])\s+", r"\1", s)                   # drop space AFTER CJK opening punct
    s = re.sub(r"([，。、！？：；])\s+(?=[A-Za-z0-9])", r"\1", s)  # drop space after CJK punct before latin/num
    s = re.sub(r"^[，,。.\s]+", "", s)
    return s


def _strip_tail(s: str) -> str:
    return re.sub(r"[。.\s]+$", "", s or "")


def _ensure_period(s: str) -> str:
    s = (s or "").strip()
    if s and s[-1] not in "。！？!?…：:；;，,、":
        s += "。"
    return s


def _findall(pat, text):
    return [_clean(x) for x in re.findall(pat, text, re.S)]


def _norm_date(d):
    if isinstance(d, (list, tuple)) and len(d) == 3:
        return int(d[0]), int(d[1]), int(d[2])
    if isinstance(d, str):
        m = re.search(r"(\d{4})\D+(\d{1,2})\D+(\d{1,2})", d)
        if m:
            return int(m.group(1)), int(m.group(2)), int(m.group(3))
    return None


def _slides(html_text):
    out = {}
    for p in re.split(r'<section class="slide"', html_text)[1:]:
        m = re.match(r'\s*id="([^"]+)"', p)
        if m:
            out[m.group(1)] = p
    return out


def _striplabel(spans, label):
    for sp in spans:
        if sp.startswith(label):
            return sp[len(label):].strip()
    return ""


def parse_html(html_text: str) -> dict:
    data = {"date": None, "headlines": [], "stories": [], "watch": []}
    dm = re.search(r'<div class="date">(.*?)</div>', html_text, re.S)
    if dm:
        data["date"] = _norm_date(_clean(dm.group(1)))
    slides = _slides(html_text)

    cover = slides.get("cover", "")
    hm = re.search(r'<div class="headline-stack"[^>]*>(.*?)</div>', cover, re.S)
    if hm:
        data["headlines"] = _findall(r"<span>(.*?)</span>", hm.group(1))

    i = 1
    while ("story-%d" % i) in slides:
        s = slides["story-%d" % i]
        st = {}
        m = re.search(r'<h2 class="news-title">(.*?)</h2>', s, re.S)
        st["title"] = _clean(m.group(1)) if m else ""
        bm = re.search(r'<div class="byline">(.*?)</div>', s, re.S)
        by = _findall(r"<span>(.*?)</span>", bm.group(1)) if bm else []
        bigs = _findall(r'<p class="big">(.*?)</p>', s)
        st["summary_main"] = bigs[0] if len(bigs) > 0 else ""
        st["why"] = bigs[1] if len(bigs) > 1 else ""
        im = re.search(r'<ul class="impact-list">(.*?)</ul>', s, re.S)
        st["impacts"] = _findall(r"<li>(.*?)</li>", im.group(1)) if im else []
        rows = re.findall(
            r'<div class="source-row"><span>(.*?)</span><span>(.*?)</span></div>', s, re.S)
        rowmap = {_clean(k): _clean(v) for k, v in rows}
        st["source"] = rowmap.get("主要来源") or _striplabel(by, "来源：")
        st["confidence"] = rowmap.get("可信度") or _striplabel(by, "可信度：")
        st["to_verify"] = rowmap.get("待验证", "")
        st["action"] = rowmap.get("建议动作", "")
        data["stories"].append(st)
        i += 1

    tm = slides.get("tomorrow", "")
    for a, b in re.findall(
            r'<div class="mini-card"><strong>(.*?)</strong><span>(.*?)</span></div>', tm, re.S):
        data["watch"].append({"title": _clean(a), "text": _clean(b)})
    return data


def build_script(data: dict) -> str:
    d = _norm_date(data.get("date"))
    L = []
    L.append("每日 AI 新闻，%d 年 %d 月 %d 日。" % d if d else "每日 AI 新闻。")
    L.append("")
    heads = [h for h in data.get("headlines", []) if h][:3]
    if heads:
        L.append("今天的主要内容是：")
        for i, h in enumerate(heads, 1):
            L.append("%s，%s。" % (cn_ordinal(i), _strip_tail(h)))
        L.append("")
    L.append("下面进入详细内容。")
    L.append("")
    for i, st in enumerate(data.get("stories", []), 1):
        L.append("第%s条，%s。" % (cn_ordinal(i), _strip_tail(st.get("title", ""))))
        if st.get("summary_main"):
            L.append(_ensure_period(st["summary_main"]))
        if st.get("why"):
            L.append("为什么重要：%s" % _ensure_period(st["why"]))
        imps = [x for x in st.get("impacts", []) if x]
        if imps:
            L.append("具体影响包括：")
            for j, im in enumerate(imps, 1):
                L.append("%s，%s。" % (cn_ordinal(j), _strip_tail(im)))
        if st.get("source"):
            L.append("信息来源：%s。" % _strip_tail(st["source"]))
        if st.get("confidence"):
            L.append("可信度：%s。" % _strip_tail(st["confidence"]))
        if st.get("to_verify"):
            L.append("待验证信息：%s。" % _strip_tail(st["to_verify"]))
        L.append("")
    watch = [w for w in data.get("watch", []) if w.get("title") or w.get("text")]
    if watch:
        L.append("明日观察：")
        for i, w in enumerate(watch, 1):
            t, x = _strip_tail(w.get("title", "")), _strip_tail(w.get("text", ""))
            L.append("%s，%s，%s。" % (cn_ordinal(i), t, x) if t and x
                     else "%s，%s。" % (cn_ordinal(i), t or x))
        L.append("")
    L.append("以上就是今天的每日 AI 新闻。")
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(L)).strip() + "\n"
    return text


def html_to_script(html_text: str) -> str:
    return build_script(parse_html(html_text))


def _default_outname(data, srcdir):
    d = _norm_date(data.get("date"))
    ds = "%04d-%02d-%02d" % d if d else "output"
    return os.path.join(srcdir, "daily-ai-news-%s-script.txt" % ds)


def main(argv=None):
    ap = argparse.ArgumentParser(description="newspaper HTML/JSON -> TTS broadcast script")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--html")
    g.add_argument("--json")
    ap.add_argument("--out", help="output .txt (default: daily-ai-news-<date>-script.txt next to source)")
    a = ap.parse_args(argv)
    if a.html:
        with open(a.html, encoding="utf-8") as f:
            data = parse_html(f.read())
        srcdir = os.path.dirname(os.path.abspath(a.html))
    else:
        with open(a.json, encoding="utf-8") as f:
            data = json.load(f)
        srcdir = os.path.dirname(os.path.abspath(a.json))
    script = build_script(data)
    out = a.out or _default_outname(data, srcdir)
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(script)
    warn = "  WARNING: unfilled {{placeholders}} present!" if "{{" in script else ""
    sys.stderr.write("[scriptgen] wrote %s (%d chars)%s\n" % (out, len(script), warn))
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
