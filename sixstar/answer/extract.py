"""Pulling the "answer" string out of a structured-output JSON stream as it arrives,
so the player sees words immediately instead of waiting for the whole object."""
from __future__ import annotations

import re

_KEY = re.compile(r'"answer"\s*:\s*"')
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", '"': '"', "\\": "\\", "/": "/"}


class AnswerStreamExtractor:
    def __init__(self) -> None:
        self.buf = ""
        self.pos = 0
        self.state = "seek"  # seek -> in -> done
        self.text = ""

    def feed(self, chunk: str) -> str:
        """Adding raw JSON text; returning any newly decoded characters of "answer"."""
        self.buf += chunk
        if self.state == "seek":
            m = _KEY.search(self.buf)
            if not m:
                return ""
            self.pos = m.end()
            self.state = "in"
        if self.state != "in":
            return ""
        out: list[str] = []
        buf, i = self.buf, self.pos
        while i < len(buf):
            c = buf[i]
            if c == "\\":
                if i + 1 >= len(buf):
                    break
                n = buf[i + 1]
                if n == "u":
                    if i + 6 > len(buf):
                        break
                    code = int(buf[i + 2 : i + 6], 16)
                    if 0xD800 <= code < 0xDC00:  # surrogate pair: wait for the low half
                        if i + 12 > len(buf):
                            break
                        if buf[i + 6 : i + 8] == "\\u":
                            low = int(buf[i + 8 : i + 12], 16)
                            out.append(chr(0x10000 + ((code - 0xD800) << 10) + (low - 0xDC00)))
                            i += 12
                            continue
                    out.append(chr(code))
                    i += 6
                    continue
                out.append(_ESCAPES.get(n, n))
                i += 2
                continue
            if c == '"':
                self.state = "done"
                i += 1
                break
            out.append(c)
            i += 1
        self.pos = i
        piece = "".join(out)
        self.text += piece
        return piece
