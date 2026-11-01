// SP15 11장: the life manager's copy in the app (partner chips, the budget line, expert notes, the
// panel suggestion card, the life report, the more screen's statements). Kept out of copy.ts so the
// first screen's bundle does not carry it: only the chat sheet's and the page chunks import it.
// scripts/lint-copy.mjs allows Korean here too. The partner's name is copy.agentNames.manager. The
// budget line names no cap, and none of the banned words (plan ruling).
export const copyPanel = {
  chips: {
    manager_full: "전체 진단",
    manager_week: "이번 주 뭐부터?",
    manager_upload: "자료 올리기",
    fullDone: "오늘은 이미 했어요",
    fullAsk: "전체 진단 해 볼까요?",
  },
  budget: (n: number) => `이번 주 제안 ${n}개 더 받을 수 있어요`,
  expertNotes: (n: number) => `전문가 소견 ${n}개`,
  experts: {
    career: "커리어 전략가",
    finance: "재무설계사",
    health: "건강 전문의",
    image: "이미지 컨설턴트",
    relationship: "관계 코치",
    psych: "심리 코치",
  },
  card: {
    minutes: (n: number) => `약 ${n}분`,
    perWeek: (n: number) => (n === 7 ? "매일" : `주 ${n}번`),
    accept: "받기",
    dismiss: "버리기",
    evidence: "근거 보기",
    groups: {
      record: "내 기록",
      statement: "내가 한 말",
      external: "외부 기준",
    },
    accepted: "받았어요",
    dismissed: "버렸어요",
    gone: "지금은 볼 수 없는 기록이에요",
  },
  reasons: {
    no_time: "시간 없음",
    not_interested: "관심 없음",
    already: "이미 하는 중",
    too_big: "너무 큼",
    none: "그냥",
  },
  reasonTitle: "버리는 이유",
  // The life manager's conversation: the secretary's sentences with the name changed (as copy.chat.mate).
  manager: {
    inputLabel: "라이프 매니저에게 보낼 말",
    queued: "라이프 매니저가 앞의 일을 끝내는 중이에요",
    thinking: "라이프 매니저가 생각하는 중이에요",
    backToChat: "‹ 라이프 매니저",
  },
  // SP15 10장: `/status/report/` (its own page's chunk) and the status screen's line to it. No "%" and no rank words.
  report: {
    title: "인생 리포트",
    link: "인생 리포트",
    empty: "아직 리포트가 없어요. 라이프 매니저에게 전체 진단을 해 보세요.",
    past: "지난 리포트",
    sections: {
      summary: "세 통로 요약",
      scores: "점수판",
      levers: "지렛대 지도",
      experts: "전문가 소견",
      scenario: "3년 하면 / 안 하면",
      roadmap: "90일 로드맵",
      thisWeek: "이번 주",
      questions: "남은 질문",
    },
    estimate: "추정",
    doIt: "하면",
    dontDo: "안 하면",
    avoid: "하지 말 것",
    // The six axes a lever can move (BE standing AXIS_LABELS, without the three innate ones).
    axes: {
      career: "직업",
      money: "경제력",
      health: "건강",
      looks: "외모",
      relations: "관계",
      intellect: "자격·학습 실적",
    },
    radarLabel: "여섯 축 레이더: 전체 점수",
    dumbbellLabel: (axis: string) => `${axis}: 전체와 IT 점수`,
    leverLabel: "지렛대 지도: 행동에서 축으로, 굵을수록 강해요",
    roadmapLabel: (track: string) => `${track} 기간`,
  },
  // SP15 5.4: the more screen's "내가 한 말" (opens in place, like "비서 메모").
  statements: {
    title: "내가 한 말",
    empty: "아직 없어요.",
    retire: "지우기",
    kinds: { fact: "사실", preference: "성향", decision: "결정" },
  },
} as const;

export type ReportAxis = keyof typeof copyPanel.report.axes;

export type ExpertKey = keyof typeof copyPanel.experts;
export type DismissReason = keyof typeof copyPanel.reasons;
