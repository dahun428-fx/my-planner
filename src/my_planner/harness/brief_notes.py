"""마스터의 아침 브리핑에 붙는 아래층 관찰 한 줄 (SP14 스펙 1장 4, 8장, T7·T13).

아래층 상대(메이트·매니저)는 먼저 말하지 않는다. 사용자에게 가는 길은 아침 브리핑 끝의 관찰 줄뿐이다.
`priority` 1은 하네스가 그대로 덧붙이고(많아야 `BRIEF_P1_MAX`), 없으면 두뇌가 `priority` 2 가운데 하나를 고른다.
보인 것으로 표시(`mark_shown`)는 전송이 끝난 뒤 디스패처가 한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from my_planner.domain import InboxAgent
    from my_planner.store.repos.agents import AgentNote

AGENT_LABELS: dict[InboxAgent, str] = {"mate": "운동메이트", "manager": "라이프 매니저"}
BRIEF_P1_MAX = 2  # 브리핑 하나에 덧붙이는 `priority` 1 줄 수
BRIEF_NOTE_DAYS = 2  # 후보 창: `day >= today - 2일`(`AgentsRepo.brief_candidates`)
BRIEF_BLOCK_HEAD = "## 아래층 관찰"
_P1_GUIDE = "하네스가 아래 줄을 메시지 끝에 그대로 붙입니다. 같은 내용을 다시 쓰지 않습니다."
_P2_GUIDE = "아래 가운데 오늘 도움이 될 줄이 있으면 하나만 골라 그대로 메시지 끝에 한 줄로 붙입니다. 없으면 붙이지 않습니다."


@dataclass(frozen=True)
class BriefNotes:
    text: str
    shown_ids: tuple[int, ...]


def note_line(n: AgentNote) -> str:
    """`"{이름}: {관찰}"`. 앱 `splitAgentNotes`가 이 모양으로 시작하는 줄을 관찰로 읽는다."""
    return f"{AGENT_LABELS[n.agent]}: {n.text}"


def _p1(cands: list[AgentNote]) -> list[AgentNote]:
    """붙일 `priority` 1: 후보 순서(`priority`, `created_at`, `id`)로 앞 `BRIEF_P1_MAX`개."""
    return [n for n in cands if n.priority == 1][:BRIEF_P1_MAX]


def brief_block(cands: list[AgentNote]) -> str:
    """두뇌에게 줄 `## 아래층 관찰`. 후보가 없으면 빈 글."""
    if not cands:
        return ""
    p1 = _p1(cands)
    if p1:
        guide, shown = _P1_GUIDE, p1
    else:
        guide, shown = _P2_GUIDE, [n for n in cands if n.priority == 2]
    return "\n".join([BRIEF_BLOCK_HEAD, guide, *(f"- {note_line(n)}" for n in shown)])


def _norm(s: str) -> str:
    return " ".join(s.split())


MATCH_SUBSTRING_MIN = 10  # 이보다 짧은 관찰은 줄 전체가 같을 때만 그 줄로 본다(짧은 말이 마스터 문장을 먹지 않게)
_BULLET = "-*•· \t"


def _match(line: str, notes: list[AgentNote]) -> AgentNote | None:
    """그 줄을 관찰 줄로 볼 첫 후보.

    글머리표·`"{이름}: "`를 뗀 줄이 관찰 본문과 같으면 맞다. 본문이 `MATCH_SUBSTRING_MIN`자 이상이면 본문이
    들어 있는 줄도 맞다(공백 정규화).
    """
    flat = _norm(line).lstrip(_BULLET)
    for n in notes:
        body = _norm(n.text)
        if not body:
            continue
        prefix = f"{AGENT_LABELS[n.agent]}:"
        bare = flat[len(prefix):].strip() if flat.startswith(prefix) else flat
        if bare == body:
            return n
        if len(body) >= MATCH_SUBSTRING_MIN and body in flat:
            return n
    return None


def settle_brief(text: str, cands: list[AgentNote]) -> BriefNotes:
    """두뇌 글의 관찰 줄을 정리한다(8장). 찾아서 남기는 줄은 줄 전체를 `note_line`으로 바꿔 쓴다.

    `priority` 1이 있으면 본문의 `priority` 2 줄은 지우고, 붙일 `priority` 1마다 이미 있으면 그 자리를, 없으면 끝에
    덧붙인다(두 번 나오지 않게). 없으면 본문의 `priority` 2 가운데 처음 나온 하나만 남긴다. 못 찾은 줄은 보인 것이 아니다.
    """
    if not cands:
        return BriefNotes(text, ())
    p1 = _p1(cands)
    p2 = [n for n in cands if n.priority == 2]
    out: list[str] = []
    kept: list[int] = []
    for line in text.split("\n"):
        if p1:
            hit = _match(line, p1)
            if hit is not None:
                if hit.id not in kept:
                    out.append(note_line(hit))
                    kept.append(hit.id)
                continue
            if _match(line, p2) is not None:
                continue
        else:
            hit = _match(line, p2)
            if hit is not None:
                if not kept:
                    out.append(note_line(hit))
                    kept.append(hit.id)
                continue
        out.append(line)
    body = "\n".join(out).rstrip()
    if not p1:
        return BriefNotes(body, tuple(kept))
    missing = [n for n in p1 if n.id not in kept]
    if missing:
        tail = "\n".join(note_line(n) for n in missing)
        body = f"{body}\n\n{tail}" if body else tail
    return BriefNotes(body, tuple(n.id for n in p1))
