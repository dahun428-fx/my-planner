#!/usr/bin/env python3
"""my-planner 산출물 — 아이콘 스프라이트 동기화.

icons.svg(원본)의 <svg>…</svg>를 줄바꿈 없이 icons.js의 SPRITE 문자열로 넣는다.
여러 번 돌려도 결과가 같다. 아이콘을 고칠 때는 icons.svg만 고치고 이 스크립트를 돌린다.
사용: python3 docs/deliverables/assets/build-icons.py
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    svg = (HERE / "icons.svg").read_text(encoding="utf-8")
    body = svg[svg.index("<svg"):].strip().replace("\n", "")
    ids = re.findall(r'<symbol id="(i-[a-z0-9-]+)"', body)
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        print("중복 id:", ", ".join(dupes), file=sys.stderr)
        return 1
    js_path = HERE / "icons.js"
    js = js_path.read_text(encoding="utf-8")
    new, n = re.subn(r'var SPRITE = ".*?";\n', lambda m: "var SPRITE = " + json.dumps(body, ensure_ascii=False) + ";\n", js, count=1, flags=re.S)
    if n != 1:
        print("icons.js에서 SPRITE 줄을 찾지 못했습니다", file=sys.stderr)
        return 1
    if new != js:
        js_path.write_text(new, encoding="utf-8")
    print(f"아이콘 {len(ids)}개 동기화")
    return 0


if __name__ == "__main__":
    sys.exit(main())
