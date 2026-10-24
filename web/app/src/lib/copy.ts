// Every Korean sentence the app shows lives here (spec 10장). Screen code takes text from `copy`;
// `npm run lint:copy` rejects Hangul literals anywhere else. Templates are functions.
// Later tickets add entries to these groups.

export const copy = {
  appName: "비서",

  tabs: {
    today: "오늘",
    todos: "할 일",
    activity: "기록",
    settings: "설정",
    navLabel: "탭",
  },

  status: {
    connected: "비서 연결됨",
    offline: "비서 오프라인",
    reLogin: "비서가 노트북에서 다시 로그인해야 해요",
    limitedUntil: (hhmm: string) => `비서가 ${hhmm}까지 답을 쉬어요`,
    telegramDown: "텔레그램 연결 끊김",
    unauthorized: "열쇠가 맞지 않아요. 설정에서 다시 넣어 주세요.",
    tooMany: "잠시 뒤에 다시 해 주세요.",
    safeMode: "노트북의 데이터베이스 점검이 필요해요. README의 복구 절차를 따라 주세요.",
    loading: "불러오는 중",
  },

  today: {
    title: "오늘",
    checkinWaiting: "답장할 수 있어요",
    needsConfirm: "확인이 필요해요",
    morePlain: "더 보기",
    condition: "오늘 컨디션",
    change: "바꾸기",
    todosHeading: (n: number) => `할 일 (${n})`,
    seeAll: "전체 보기",
    noTodos: "오늘 잡힌 할 일이 없어요. 비서에게 말하거나 + 로 추가할 수 있어요.",
    completedAt: (hhmm: string) => `${hhmm} 완료`,
    pinnedBy: "비서가 올려 둔 카드",
  },

  chat: {
    launcher: "비서에게 말하기",
    launcherOffline: "비서가 다시 연결되면 말할 수 있어요",
    close: "닫기",
    title: "비서",
    subtitle: "앱 대화",
    queued: "비서가 앞의 일을 끝내는 중이에요",
    elsewhere: "다른 곳에서 바뀐 것: ",
    send: "보내기",
    undo: "되돌리기",
  },

  checkin: {
    back: "‹ 오늘",
    canReply: "답장할 수 있어요",
    answeredVia: (channel: string) => `${channel}에서 답했어요`,
    passed: "지나감",
    sentAt: (hhmm: string) => `${hhmm}에 보냄`,
    receivedApp: "앱 알림으로 받음",
    receivedTelegram: "텔레그램으로 받음",
  },

  todos: {
    title: "할 일",
    add: "할 일 추가",
    periods: {
      today: "오늘",
      week: "이번 주",
      month: "이번 달",
      quarter: "분기",
      year: "올해",
    },
    emptyDay: (weekday: string) => `${weekday} · 없음`,
    tomorrow: "내일로",
    drop: "빼기",
    drafts: (n: number) => `초안 (${n})`,
    draftsHint: "확정하면 할 일이 돼요",
    confirm: "확정",
    confirmAll: "모두 확정",
  },

  activity: {
    title: "기록",
    intro: "비서와 내가 바꾼 것. 가벼운 변경은 24시간 안에 되돌릴 수 있어요.",
    undo: "되돌리기",
    undoneAt: (hhmm: string) => `${hhmm}에 되돌림`,
    more: "더 보기",
  },

  settings: {
    title: "설정",
    connection: "비서 연결",
    notify: "체크인 알림",
    schedule: "체크인 시간",
    pause: "쉬어 가기",
    device: "이 기기",
    about: "정보",
    disconnect: "이 기기 연결 해제",
    themeSystem: "시스템 따라",
    themeLight: "밝게",
    themeDark: "어둡게",
  },

  connect: {
    title: "노트북의 비서와 연결해요",
    intro: "한 번만 하면 돼요. 주소와 열쇠는 이 폰에만 저장되고 어디에도 올라가지 않아요.",
    ok: "연결 확인됨 · 비서가 답했어요",
    badToken: "열쇠가 맞지 않아요",
    unreachable: "주소에 닿지 않아요. 노트북과 폰의 Tailscale을 확인해 주세요.",
  },

  offline: {
    lead: "노트북의 비서에 닿지 않아요.",
    snapshotAt: (hhmm: string) => `아래는 ${hhmm}에 받은 내용이고, 지금은 볼 수만 있어요.`,
    noSnapshot: "아직 받아 둔 내용이 없어요. 노트북이 켜지면 보여 드릴게요.",
    reconnect: "다시 연결",
    check: "연결 확인",
  },

  errors: {
    block: (code: string) => `이 부분을 불러오지 못했어요 (${code})`,
    retry: "다시 시도",
    notFound: "찾는 화면이 없어요.",
    goToday: "오늘로 가기",
  },

  parts: {
    unknown: "이 카드는 아직 이 앱에서 보여 줄 수 없어요.",
  },

  areas: {
    career: "커리어",
    finance: "경제",
    health: "건강",
    relationships: "관계",
    learning: "배움",
    quality_of_life: "삶의 질",
  },

  loops: {
    morning_brief: "아침 브리핑",
    evening_checkin: "저녁 체크인",
    review: "주간 회고",
    return: "다시 이어서",
  },

  channels: {
    app: "앱",
    app_chat: "앱 대화",
    telegram: "텔레그램",
  },

  actors: {
    secretary: "비서",
    user: "나",
  },

  common: {
    close: "닫기",
  },
} as const;

export type Copy = typeof copy;
