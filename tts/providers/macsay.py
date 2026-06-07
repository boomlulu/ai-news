"""Zero-dependency FALLBACK provider using macOS `say`. Always available on macOS.
Not the primary voice — guarantees the pipeline + a sample audio even before
CosyVoice is installed. Maps the sweet-female profile to the Tingting (婷婷) voice."""
from __future__ import annotations
import os
import shutil
import subprocess
import sys
import tempfile
from .base import TTSProvider, TTSRequest, TTSResult


class MacSayProvider(TTSProvider):
    name = "macsay"

    def is_available(self):
        if sys.platform != "darwin":
            return False, "macsay only on macOS"
        if shutil.which("say") is None:
            return False, "`say` not found"
        return True, "ok"

    def synthesize(self, req: TTSRequest) -> TTSResult:
        ok, why = self.is_available()
        if not ok:
            return TTSResult(None, "unavailable", self.name, why)
        say_voice = req.extra.get("say_voice", "Tingting")
        base_rate = int(req.extra.get("say_base_rate", 170))  # say -r = words/min
        rate = max(80, int(base_rate * float(req.speed or 1.0)))
        out = os.path.abspath(req.output_path)
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        aiff = txt_path = None
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                             encoding="utf-8") as tx:
                tx.write(req.text)
                txt_path = tx.name
            with tempfile.NamedTemporaryFile(suffix=".aiff", delete=False) as tf:
                aiff = tf.name
            subprocess.run(["say", "-v", say_voice, "-r", str(rate),
                            "-f", txt_path, "-o", aiff],
                           check=True, capture_output=True)
            ext = os.path.splitext(out)[1].lower().lstrip(".") or "wav"
            if ext == "aiff":
                shutil.move(aiff, out)
            else:
                ff = shutil.which("ffmpeg")
                if ff is None:
                    out = os.path.splitext(out)[0] + ".aiff"
                    shutil.move(aiff, out)
                else:
                    subprocess.run([ff, "-y", "-i", aiff, out],
                                   check=True, capture_output=True)
                    os.remove(aiff)
                    aiff = None
            return TTSResult(out, "ok", self.name,
                             meta={"say_voice": say_voice, "rate": rate})
        except subprocess.CalledProcessError as e:
            err = (e.stderr or b"").decode("utf-8", "ignore")
            return TTSResult(None, "error", self.name, err or str(e))
        except Exception as e:
            return TTSResult(None, "error", self.name, str(e))
        finally:
            for p in (txt_path, aiff):
                if p and os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
