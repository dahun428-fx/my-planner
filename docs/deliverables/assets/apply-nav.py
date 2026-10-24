#!/usr/bin/env python3
"""my-planner 산출물 v2 — 문서 목록과 상단 막대 맞추기 (컨트롤러가 마지막에 한 번 돌린다).

하는 일 (docs/deliverables/*.html 모두):
  1. <nav class="docnav" …>…</nav> 블록을 assets/nav.html 내용으로 바꾼다.
     원래 블록의 들여쓰기를 지킨다. docnav가 없는 페이지(포털 index)는 건너뛴다.
  2. <div class="topbar__doc"><span>…</span></div>의 글자를 TOPBAR_TEXT로 바꾼다.

여러 번 돌려도 결과가 같다(멱등). 바뀐 파일만 다시 쓴다.
사용:
  python3 docs/deliverables/assets/apply-nav.py           # 적용
  python3 docs/deliverables/assets/apply-nav.py --check   # 바꿀 파일만 보여 주고 쓰지 않음 (바꿀 것이 있으면 종료 코드 1)
"""
import re
import sys
from pathlib import Path

ASSETS = Path(__file__).resolve().parent
SITE = ASSETS.parent
TOPBAR_TEXT = "v2 · 전체 시스템 · main 722d0d6"

NAV_RE = re.compile(r'^([ \t]*)<nav class="docnav"[^>]*>.*?</nav>[ \t]*$', re.S | re.M)
TOPBAR_RE = re.compile(r'(<div class="topbar__doc"><span>)(.*?)(</span></div>)', re.S)


def load_nav() -> list[str]:
    text = (ASSETS / "nav.html").read_text(encoding="utf-8").strip("\n")
    lines = text.split("\n")
    base = min(len(l) - len(l.lstrip(" ")) for l in lines if l.strip())
    return [l[base:] for l in lines]


def apply(html: str, nav_lines: list[str]) -> tuple[str, list[str]]:
    notes = []
    m = NAV_RE.search(html)
    if m:
        indent = m.group(1)
        block = "\n".join((indent + l) if l.strip() else "" for l in nav_lines)
        if m.group(0) != block:
            html = html[: m.start()] + block + html[m.end():]
            notes.append("docnav")
    t = TOPBAR_RE.search(html)
    if t and t.group(2) != TOPBAR_TEXT:
        html = html[: t.start()] + t.group(1) + TOPBAR_TEXT + t.group(3) + html[t.end():]
        notes.append("topbar")
    return html, notes


def main(argv: list[str]) -> int:
    check = "--check" in argv
    nav_lines = load_nav()
    pending = 0
    for path in sorted(SITE.glob("*.html")):
        old = path.read_text(encoding="utf-8")
        new, notes = apply(old, nav_lines)
        has_nav = bool(NAV_RE.search(old))
        if not notes:
            print(f"그대로   {path.name}" + ("" if has_nav else "  (docnav 없음)"))
            continue
        pending += 1
        if check:
            print(f"바꿀 것  {path.name}: {', '.join(notes)}")
        else:
            path.write_text(new, encoding="utf-8")
            print(f"바꿈     {path.name}: {', '.join(notes)}")
    if check and pending:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
