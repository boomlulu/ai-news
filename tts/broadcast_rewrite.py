"""Rewrite a deterministic field-version script (or newspaper HTML) into a
high-density Chinese TTS broadcast script via an LLM "fact down-toning" pass.

    field script / HTML  ->  daily-ai-news-YYYY-MM-DD-broadcast.txt

The LLM pass uses the `claude -p` CLI driven by tts/broadcast_prompt.md (the
single source of truth for the 事实降调 / down-toning rules). Following the same
"永不抛异常" philosophy as tts_service: if claude is missing, times out, exits
non-zero, returns empty, or anything else goes wrong, this falls back to writing
the deterministic field-version text verbatim instead of raising.
"""
from __future__ import annotations
import argparse
import os
import re
import shutil
import subprocess
import sys

_CLAUDE_FALLBACK = "/Users/boom/.local/bin/claude"


def _date_from_name(path: str) -> str:
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", os.path.basename(path or ""))
    return "%s-%s-%s" % (m.group(1), m.group(2), m.group(3)) if m else "output"


def _cn_count(t: str) -> int:
    return len(re.findall(r"[一-鿿]", t or ""))


def _post(t: str) -> str:
    t = (t or "").strip()
    if "```" in t:
        t = "\n".join(ln for ln in t.splitlines() if not ln.lstrip().startswith("```"))
    return t.strip("\n").strip()


def _claude_bin():
    return shutil.which("claude") or _CLAUDE_FALLBACK


def _run_claude(prompt: str, timeout: int = 300) -> str:
    claude = _claude_bin()
    if not (claude and os.path.exists(claude)):
        raise RuntimeError("claude binary not found")
    r = subprocess.run([claude, "-p", prompt], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError("claude exit %d: %s" % (r.returncode, (r.stderr or "").strip()[:200]))
    out = _post(r.stdout)
    if not out:
        raise RuntimeError("claude returned empty output")
    return out


def main(argv=None):
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(
        description="field script / HTML -> high-density TTS broadcast script (LLM 降调改写)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--script", help="field-version .txt (from tts.scriptgen)")
    g.add_argument("--html", help="newspaper HTML (converted to field text via tts.scriptgen)")
    ap.add_argument("--out", help="output .txt (default: daily-ai-news-<date>-broadcast.txt next to source)")
    ap.add_argument("--no-llm", action="store_true",
                    help="skip the LLM pass; write the field text verbatim (test / deterministic fallback)")
    ap.add_argument("--prompt", default=os.path.join(here, "broadcast_prompt.md"),
                    help="editor prompt template (default: tts/broadcast_prompt.md)")
    a = ap.parse_args(argv)

    # Resolve field text + source dir.
    if a.script:
        src = os.path.abspath(a.script)
        with open(src, encoding="utf-8") as f:
            field_text = f.read()
    else:
        from tts import scriptgen
        src = os.path.abspath(a.html)
        with open(src, encoding="utf-8") as f:
            field_text = scriptgen.html_to_script(f.read())
    srcdir = os.path.dirname(src)

    out = a.out or os.path.join(srcdir, "daily-ai-news-%s-broadcast.txt" % _date_from_name(src))
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)

    result = None
    via = "fallback"

    if not a.no_llm:
        try:
            with open(a.prompt, encoding="utf-8") as f:
                template = f.read()
            full = (template +
                    "\n\n----\n以下是今天的日报原始内容（字段版），据此产出最终口播稿，"
                    "直接输出纯文本口播稿，不要解释：\n\n" + field_text)
            text = _run_claude(full)
            if _cn_count(text) > 1300:
                try:
                    text = _run_claude(
                        "把下面口播稿压缩到 1300 个中文字符以内，保持结构，不要解释，直接输出：\n\n" + text)
                except Exception:
                    pass  # second pass failed -> accept the (over-long) first pass
            result = text
            via = "claude"
        except Exception as e:  # never raise: fall back to field version
            sys.stderr.write(
                "[broadcast_rewrite] WARNING claude unavailable/failed -> "
                "fell back to field-version (%s)\n" % e)
            result = None

    if result is None:
        result = _post(field_text) or field_text.strip()
        via = "fallback"

    with open(out, "w", encoding="utf-8") as f:
        f.write(result.rstrip("\n") + "\n")
    sys.stderr.write("[broadcast_rewrite] wrote %s (%d 中文字符, via=%s)\n"
                     % (out, _cn_count(result), via))
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
