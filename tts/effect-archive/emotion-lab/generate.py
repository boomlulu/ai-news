#!/usr/bin/env python3
"""女生情绪库评测 harness：读 taxonomy.json -> CosyVoice2 instruct2 合成 -> mp3 -> 评分表。

Run (must set PYTHONPATH to repo root so `from tts import tts_service` resolves):

    PYTHONPATH=/Users/boom/Demo/AINews \
      tts/.venv/bin/python tts/effect-archive/emotion-lab/generate.py \
      [--round round-01] [--only 01,02] [--variants v1,v3] [--text-set primary|all|daily,scene]

每次 run 覆盖该 round 目录里同名文件（不做"已生成跳过"逻辑）。
"""
import os
import json
import argparse
import tempfile
import subprocess

from tts import tts_service

HERE = os.path.dirname(os.path.abspath(__file__))
TAXONOMY = os.path.join(HERE, "taxonomy.json")


def load_taxonomy():
    with open(TAXONOMY, "r", encoding="utf-8") as f:
        return json.load(f)


def safe_name(s):
    # 文件名里禁出现路径分隔符；slug 里只有 - 与中文，保险起见替换 / 与空白
    return s.replace("/", "_").replace(" ", "").strip()


def to_mp3(wav_path, mp3_path):
    """ffmpeg: wav -> mp3 (libmp3lame -q:a 2)。返回 (ok, err)。"""
    cmd = [
        "ffmpeg", "-y", "-i", wav_path,
        "-codec:a", "libmp3lame", "-q:a", "2",
        mp3_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return False, (proc.stderr or "").strip().splitlines()[-1:] or ["ffmpeg failed"]
    return True, None


def safe_texts(emo, text_set):
    """返回 [(text_id, text)]；默认只用 emo['text']，可展开 texts 分组。"""
    if text_set == "primary" or "texts" not in emo:
        return [("primary", emo["text"])]

    groups = emo.get("texts", {})
    wanted = list(groups) if text_set == "all" else [
        x.strip() for x in text_set.split(",") if x.strip()
    ]
    texts = []
    for group in wanted:
        for idx, text in enumerate(groups.get(group, []), 1):
            texts.append((f"{group}{idx}", text))
    return texts or [("primary", emo["text"])]


def build_jobs(tax, only, variants, text_set):
    """展开成 [(emo, var, text_id, text)]，可过滤情绪 id 和文本组。"""
    jobs = []
    for emo in tax["emotions"]:
        if only and emo["id"] not in only:
            continue
        for text_id, text in safe_texts(emo, text_set):
            for var in emo["variants"]:
                if variants and var["v"] not in variants:
                    continue
                jobs.append((emo, var, text_id, text))
    return jobs


def write_scoring(outdir, rows, round_name):
    """生成 SCORING.md：每条只填两列（有Bug / 可用），按情绪分组。"""
    lines = []
    lines.append(f"# 评分表 — {round_name}")
    lines.append("")
    lines.append("听 `*.mp3`，每条只填两列。")
    lines.append("有Bug：吞字/读错/电音/杂音/削音/停顿怪 → 填 `Y`，无则留空；可用：能用 → 填 `√`，不能用留空。")
    lines.append("")
    lines.append("| 序号 | 情绪 | 变体 | 文件 | instruct | 有Bug | 可用 | 优化建议 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    last_emo = None
    for r in rows:
        # 同情绪只在第一行展示情绪名，分组更清晰（后续行留空）
        emo_cell = r["emo_name"] if r["emo_id"] != last_emo else ""
        last_emo = r["emo_id"]
        status = "" if r["ok"] else " (合成失败)"
        lines.append(
            f"| {r['emo_id']} | {emo_cell} | {r['v']} | `{r['fname']}`{status} | "
            f"{r['instruct']} |  |  |  |"
        )
    lines.append("")
    path = os.path.join(outdir, "SCORING.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


def rescore(outdir, tax, round_name):
    """从 outdir 现有 *.mp3 重建 SCORING.md，不调 TTS（已合成不重跑）。"""
    import glob

    mp3s = sorted(glob.glob(os.path.join(outdir, "*.mp3")))
    if not mp3s:
        print("[warn] no mp3 in outdir; nothing to rescore.")
        return

    # taxonomy 索引：emo_id -> {name, variants{v: instruct}}
    by_id = {}
    for emo in tax["emotions"]:
        by_id[emo["id"]] = {
            "name": emo["name"],
            "variants": {var["v"]: var["instruct"] for var in emo["variants"]},
        }

    rows = []
    for path in mp3s:
        fname = os.path.basename(path)
        base = fname[:-4] if fname.endswith(".mp3") else fname
        parts = base.split("__")
        if len(parts) == 3:
            text_id, v = "primary", parts[1]
        elif len(parts) == 4:
            text_id, v = parts[1], parts[2]
        else:
            print(f"[warn] skip (unexpected name): {fname}")
            continue

        head = parts[0]
        emo_id, _name = head.split("_", 1)
        emo = by_id.get(emo_id)
        if emo is None:
            emo_name = emo_id
            instruct = ""
        else:
            emo_name = emo["name"]
            instruct = emo["variants"].get(v, "")

        rows.append({
            "emo_id": emo_id, "emo_name": emo_name, "v": v,
            "text_id": text_id, "fname": fname, "instruct": instruct, "ok": True,
        })

    rows.sort(key=lambda r: (r["emo_id"], r["text_id"], r["v"]))
    scoring = write_scoring(outdir, rows, round_name)
    print(f"[emotion-lab] rescore: {len(rows)} rows -> {scoring}")


def main():
    ap = argparse.ArgumentParser(description="emotion-lab generator")
    ap.add_argument("--round", default="round-01", help="输出子目录名，如 round-01 / _smoke")
    ap.add_argument("--only", default="", help="只跑这些情绪 id，逗号分隔，如 01,02")
    ap.add_argument("--variants", default="", help="只跑这些变体编号，逗号分隔，如 v1,v3,v7")
    ap.add_argument(
        "--text-set",
        default="primary",
        help="文本选择：primary 只跑 text；all 跑所有 texts；或 daily,scene,contrast",
    )
    ap.add_argument(
        "--rescore",
        action="store_true",
        help="不合成，从该 round 现有 *.mp3 重建 SCORING.md",
    )
    args = ap.parse_args()

    only = {x.strip() for x in args.only.split(",") if x.strip()}
    variants = {x.strip() for x in args.variants.split(",") if x.strip()}
    tax = load_taxonomy()
    outdir = os.path.join(HERE, args.round)
    os.makedirs(outdir, exist_ok=True)

    if args.rescore:
        rescore(outdir, tax, args.round)
        return

    jobs = build_jobs(tax, only, variants, args.text_set)
    total = len(jobs)
    if total == 0:
        print("[warn] no jobs matched --only filter; nothing to do.")
        return

    print(f"[emotion-lab] round={args.round} voice={tax['voice']} mode={tax['mode']} "
          f"jobs={total} outdir={outdir}")
    print("[emotion-lab] 模型首条 ~8s 加载一次，之后逐条更快。")

    rows = []
    ok_n = 0
    fail_n = 0
    for i, (emo, var, text_id, text) in enumerate(jobs, 1):
        text_part = "" if text_id == "primary" else f"__{safe_name(text_id)}"
        fname = f"{emo['id']}_{safe_name(emo['name'])}{text_part}__{var['v']}__{safe_name(var['slug'])}.mp3"
        mp3_path = os.path.join(outdir, fname)
        ok = False
        tmp_wav = None
        try:
            fd, tmp_wav = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
            r = tts_service.synthesize(
                text=text,
                output_path=tmp_wav,
                provider="cosyvoice",
                voice=tax["voice"],
                fallback="",
                mode=tax["mode"],
                instruct=var["instruct"],
            )
            if getattr(r, "ok", False):
                mok, merr = to_mp3(tmp_wav, mp3_path)
                if mok:
                    ok = True
                else:
                    print(f"  [{i}/{total}] FAIL ffmpeg {fname}: {merr}")
            else:
                reason = getattr(r, "detail", None) or getattr(r, "status", "synth error")
                print(f"  [{i}/{total}] FAIL synth {fname}: {reason}")
        except Exception as e:  # noqa: BLE001 — 单条失败不该中断全批
            print(f"  [{i}/{total}] FAIL exc {fname}: {e!r}")
        finally:
            if tmp_wav and os.path.exists(tmp_wav):
                os.remove(tmp_wav)

        if ok:
            ok_n += 1
            print(f"  [{i}/{total}] ok   {fname}")
        else:
            fail_n += 1

        rows.append({
            "emo_id": emo["id"], "emo_name": emo["name"], "v": var["v"],
            "text_id": text_id, "fname": fname, "instruct": var["instruct"], "ok": ok,
        })

    scoring = write_scoring(outdir, rows, args.round)
    print(f"[emotion-lab] done: ok={ok_n} fail={fail_n} / {total}")
    print(f"[emotion-lab] scoring -> {scoring}")


if __name__ == "__main__":
    main()
