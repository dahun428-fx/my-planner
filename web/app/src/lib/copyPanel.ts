// SP15 11장: the life manager's copy in the app (partner chips, the budget line, expert notes, the
// panel suggestion card). Kept out of copy.ts so the first screen's bundle does not carry it: only
// the chat sheet's chunk imports it. scripts/lint-copy.mjs allows Korean here too. The partner's
// name is copy.agentNames.manager. The budget line names no cap, and none of the banned words (plan ruling).
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
} as const;

export type ExpertKey = keyof typeof copyPanel.experts;
export type DismissReason = keyof typeof copyPanel.reasons;
