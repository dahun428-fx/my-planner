import type { Habit, Todo } from "../api/types.gen";

// Every Korean sentence the app shows lives here (spec 10장). Screen code takes text from `copy`;
// `npm run lint:copy` rejects Hangul literals anywhere else. Templates are functions.
// Later tickets add entries to these groups.

const CHAT_LATER = "비서가 다시 연결되면 말할 수 있어요";
// The back link of the check-in detail.
const BACK_TODAY = "‹ 오늘";
// SP9 9.1: the back link of every screen reached from the more screen.
const BACK_MORE = "‹ 더보기";
// SP9 10장 체크인 시간의 토스트와 깨우기 안내. SP9b 일정 정리 알림도 같은 문장(5장).
const FROM_TODAY = "오늘부터 적용돼요";
const FROM_TOMORROW = "내일부터 적용돼요";
const WAKE_STALE = "노트북을 깨우는 시각은 아직 그대로예요. register_task.ps1을 다시 실행해 주세요.";

export const copy = {
  appName: "비서",

  // SP9 9.1, 10장 "탭" (verbatim).
  tabs: {
    today: "오늘",
    todos: "할 일",
    schedule: "스케줄",
    memos: "메모",
    navLabel: "탭",
  },

  // SP9 9.1, 10장 "더보기" row (verbatim).
  more: {
    title: "더보기",
    settings: "설정",
    activity: "기록",
    habits: "습관",
    status: "상태창",
    connect: "기기 연결",
    back: BACK_MORE,
  },

  // SP9 9.4 memos tab and its view/write screen. 10장 rows "메모 빈 목록", "메모 충돌", "메모 확인",
  // "메모 상한", "메모 오류" verbatim (the confirmations, limits and most errors are the BE's words; they
  // are here so the banned-word check covers them and a missing BE message has the same text).
  // Labels marked (9.4) are the spec's words; those marked (new) are not in the spec and go to Dahun in SP9-12.
  memos: {
    title: "메모",
    add: "새 메모", // (new) the "+" button's name
    search: "검색", // (new) the search box's name
    pinnedHeading: "고정됨", // (9.4)
    listHeading: "메모", // (9.4)
    empty: "아직 메모가 없어요. 떠오르는 걸 적어 두세요.",
    noMatch: "맞는 메모가 없어요.", // (new) a search that finds nothing
    more: "더 보기",
    pin: "고정", // (9.4)
    unpin: "고정 풀기", // (9.4)
    delete: "지우기", // (9.4)
    bySecretary: "비서", // (9.4) SP6 mark of what the secretary made
    today: (hhmm: string) => `오늘 ${hhmm}`, // (9.4)
    yesterday: "어제", // (9.4)
    conflict: "다른 곳에서 바뀌었어요. 새로 불러올게요.",
    back: "‹ 메모", // (new) the view/write screen's back link
    body: "메모 내용", // (new) the text box's name
    noArea: "영역 없음", // (6.4)
    toolbar: {
      label: "서식", // (new) the tool row's name
      list: "목록", // (9.4)
      checkbox: "체크박스", // (9.4)
      bold: "굵게", // (9.4)
      area: "영역", // (9.4)
      done: "완료", // (9.4)
    },
    confirm: {
      created: (title: string) => `✓ 메모를 만들었어요: ${title}`,
      updated: (title: string) => `✓ 메모를 고쳤어요: ${title}`,
      pinned: (title: string) => `✓ 메모를 고정했어요: ${title}`,
      unpinned: (title: string) => `✓ 메모 고정을 풀었어요: ${title}`,
      deleted: (title: string) => `✓ 메모를 지웠어요: ${title}`,
    },
    limits: {
      too_many_memos: "메모는 2,000개까지 둘 수 있어요. 안 쓰는 메모를 지우면 새로 만들 수 있어요.",
      too_many_pinned: "고정은 10개까지예요. 다른 메모의 고정을 풀면 더 고정할 수 있어요.",
    },
    errors: {
      empty: "메모가 비어 있어요.",
      tooLong: "메모는 20,000자까지 쓸 수 있어요.",
      notFound: "없는 메모예요.",
      onlyAsked: "사용자가 부탁한 메모만 만들 수 있어요.",
      updatedAt: "updated_at은 앞서 받은 메모의 updated_at 값으로 보내 주세요.",
      query: "찾을 말(query)을 알려 주세요.",
      limit: "limit은 1~20 사이 정수예요.",
      unavailable: "메모를 다룰 수 없어요.",
    },
  },

  // SP9 9.2 스케줄 탭과 추가·상세 시트. 10장 "스케줄 빈 날", "알림 고르기", "반복", "일정 때", "일정 확인 요청"은 그대로.
  // (9.2)는 스펙 9.2의 말, (new)는 스펙에 없는 말이라 SP9-12에서 Dahun에게 묻는다.
  schedule: {
    title: "스케줄",
    month: (m: number) => `${m}월`, // (9.2) 큰 제목 = 보고 있는 달
    monthOf: (y: number, m: number) => `${y}년 ${m}월`, // (new) 펼친 달력의 머리
    prevMonth: "이전 달", // (new)
    nextMonth: "다음 달", // (new)
    week: "한 주", // (new) 한 주 띠의 이름
    hasEvents: (day: string) => `${day} · 일정 있음`, // (new) 점이 있는 날의 읽는 이름(점은 눈으로만 보인다)
    add: "일정 추가", // 10장 퀵 칩 "일정 추가"와 같은 말
    empty: "이날은 일정이 없어요.",
    allDay: "하루 종일", // (9.2)
    repeating: "반복", // (new) 반복 표시의 읽는 이름
    bySecretary: "비서", // (9.2) SP6 비서 표시
    addTitle: "일정 추가",
    editTitle: "일정 고치기", // (new)
    titleLabel: "제목",
    dateLabel: "날짜",
    timeLabel: "시각",
    repeatLabel: "반복",
    weekdaysLabel: "요일", // (new)
    remindLabel: "알림",
    areaLabel: "영역",
    noteLabel: "메모",
    addSubmit: "추가",
    save: "저장",
    close: "닫기",
    repeat: { none: "반복 없음", daily: "매일", weekly: "매주", monthly: "매달" },
    remind: { 0: "정시", 10: "10분 전", 30: "30분 전", 60: "1시간 전", 1440: "하루 전", none: "알림 없음" },
    remindLine: (label: string) => `알림 ${label}`, // 10장 "· 알림 {알림 고르기}"
    edit: "고치기", // (9.2)
    skipOne: "이번만 건너뛰기",
    endFollowing: "이후 반복 끝내기",
    deleteAll: "모두 지우기",
    delete: "지우기", // (9.2) 한 번짜리
    skip: "건너뛰기", // (9.2) 반복 일정 줄을 밀었을 때
    keep: "그대로 두기",
    // 10장 "일정 확인 요청"
    askOne: (title: string, md: string) => `이번만 건너뛰어요: ${title} (${md})`,
    askFollowing: (title: string, md: string) => `이후 반복을 끝내요: ${title} (${md}부터)`,
    askAll: (title: string) => `일정을 지워요: ${title}`,
    // 10장 "일정 때": {M/D} {HH:MM} · {M/D} 하루 종일 · 매일 {HH:MM} · 매주 {월·수} {HH:MM} · 매달 {D}일 {HH:MM}
    md: (m: number, d: number) => `${m}/${d}`,
    everyDay: (at: string) => `매일 ${at}`,
    everyWeek: (days: string, at: string) => `매주 ${days} ${at}`,
    everyMonth: (d: number, at: string) => `매달 ${d}일 ${at}`,
    weekdays: ["월", "화", "수", "목", "금", "토", "일"],
  },

  // SP8 10.2, appendix A (verbatim). Named apart from `status` above, the connection dot's words.
  // The amounts take a number or anything `Number()` reads, so the sample calls of copy.test.ts do not throw.
  statusScreen: {
    heading: "상태창",
    back: BACK_MORE,
    offline: "연결되면 상태창을 보여 드릴게요.",
    level: (n: number) => `Lv. ${n}`,
    xp: (into: number, forNext: number) => `${into} / ${forNext} XP`,
    xpBar: (into: number, forNext: number) => `경험치 ${into} / ${forNext}`,
    statsHeading: "스탯",
    noScore: "—",
    statSub: (base: number, bonus: number) => (Number(bonus) > 0 ? `바탕 ${base} · 요즘 +${Number(bonus).toFixed(1)}` : `바탕 ${base}`),
    statSubNoBase: (bonus: number) =>
      Number(bonus) > 0 ? `요즘 +${Number(bonus).toFixed(1)} · 분기 회고에서 점수를 정하면 더해져요` : "분기 회고에서 점수를 정하면 더해져요",
    recentHeading: "요즘 손이 간 영역",
    recentLine: (bonus: number) => `+${Number(bonus).toFixed(1)}`,
    recentCounts: (c: { tasks: number; habit_checks: number; body_days: number }) =>
      `4주 동안 ${[
        c.tasks > 0 ? `할 일 ${c.tasks}개` : "",
        c.habit_checks > 0 ? `습관 ${c.habit_checks}번` : "",
        c.body_days > 0 ? `몸 기록 ${c.body_days}일` : "",
      ]
        .filter(Boolean)
        .join(" · ")}`,
    recentAreasEmpty: "4주 안에 끝낸 할 일이나 습관 체크가 생기면 여기에 보여요.",
    // 10.2 body line under health: a part with no value is left out; no warning when the last record is old.
    bodyLine: (b: { steps_avg_7: number | null; sleep_avg_7: number | null }) => {
      const parts: string[] = [];
      if (typeof b.steps_avg_7 === "number") parts.push(`지난 7일 걸음 평균 ${b.steps_avg_7.toLocaleString("ko-KR")}`);
      if (typeof b.sleep_avg_7 === "number")
        parts.push(`${typeof b.steps_avg_7 === "number" ? "" : "지난 7일 "}잠 평균 ${Math.floor(b.sleep_avg_7 / 60)}시간 ${b.sleep_avg_7 % 60}분`);
      // Nothing to say when neither average exists (a record older than a week): no line, no warning.
      return parts.length > 0 ? ["몸 기록", ...parts].join(" · ") : "";
    },
    bodyLast: (date: string) => `마지막 기록 ${Number(String(date).slice(5, 7))}/${Number(String(date).slice(8, 10))}`,
    bodyConnect: "아이폰 단축어로 걸음과 잠을 보내면 건강 스탯의 근거가 돼요. 설정은 README의 'iPhone 단축어'를 봐 주세요.",
    // 10.2 moments block, appendix A (verbatim).
    momentsHeading: "이룬 순간",
    momentsEmpty: "하루가 끝나면 비서가 그날 해낸 일을 몇 줄로 남겨 둬요.",
    hiddenGroup: (n: number) => `숨긴 순간 ${n}개`,
    older: "지난 순간 더 보기",
    olderNone: "더 없어요.", // H4 N5: an older page came back with nothing new
    hide: "숨기기",
    delete: "지우기",
    unhide: "다시 보이기",
    more: "더 보기",
    hidden: "숨겼어요",
    unhidden: "다시 보여요",
    deleteAsk: "이 순간을 지울까요? 되돌릴 수 없어요.",
    deleteGo: "지우기",
    deleteKeep: "그대로 두기",
  },

  status: {
    connected: "비서 연결됨",
    offline: "비서 오프라인",
    relogin: "비서가 노트북에서 다시 로그인해야 해요",
    limited: (hhmm: string) => `비서가 ${hhmm}까지 답을 쉬어요`,
    reconnected: "다시 연결됐어요",
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
    pinnedBySecretary: "비서가 올려 둔 카드",
    pinnedMenu: "이 카드에 할 수 있는 일",
    pinnedMore: (title: string) => `${title} 카드 메뉴`,
    pinnedFallbackTitle: "고정 카드",
    unpin: "내리기",
    moveUp: "위로",
    moveDown: "아래로",
    priority: "우선",
    lessPlain: "접기",
    dateLine: (m: number, d: number, weekday: string) => `${m}월 ${d}일 ${weekday}요일`,
    checkinLine: (name: string) => `${name} · 답장할 수 있어요`,
    conditionScore: (n: number) => `컨디션 ${n}`,
    checkLabel: (title: string) => `${title} 체크`,
    doneLabel: (title: string) => `${title} 완료됨, 다시 열기`,
    menu: "이 할 일에 할 수 있는 일",
    moreActions: (title: string) => `${title} 더 보기`,
    // SP9 9.3, 10장 "놓친 알림"·"못 보낸 알림" (그대로). "오늘 일정"은 9.3의 블록 이름.
    events: "오늘 일정",
    moreEvents: (n: number) => `스케줄에서 ${n}개 더 보기`,
    missed: (hhmm: string, title: string) => `놓친 알림 · ${hhmm} ${title}`,
    unsent: (hhmm: string, title: string) => `알림을 못 보냈어요 · ${hhmm} ${title}`,
    dismissMissed: (title: string) => `${title} 알림 닫기`, // (new) 놓친 알림 줄의 × 이름
  },

  chat: {
    launcher: "비서에게 말하기",
    launcherOffline: CHAT_LATER,
    close: "닫기",
    title: "비서",
    subtitle: "앱 대화",
    queued: "비서가 앞의 일을 끝내는 중이에요",
    thinking: "비서가 생각하는 중이에요",
    elsewhere: (summary: string) => `다른 곳에서 바뀐 것: ${summary}`,
    newConversation: "새 대화",
    notReceived: "답을 받지 못했어요",
    retry: "다시 받기",
    send: "보내기",
    inputLabel: "비서에게 보낼 말",
    undo: "되돌리기",
    undone: "되돌렸어요",
    // SP9 9.6: the one line of a change before R4b (no confirmation came, only undo ids).
    changed: "✓ 바꿨어요",
    changedMany: (n: number) => `✓ ${n}개를 바꿨어요`,
    undonePartly: (k: number) => `${k}개만 되돌렸어요`,
    messages: "대화 내용",
    // SP9 9.5 대화 목록. 10장 "대화 목록" row verbatim (pastConversations, newConversation, deleteAsk);
    // marked (9.5) are the section's words; (new) are not in the spec and go to Dahun in SP9-12.
    pastConversations: "지난 대화",
    deleteAsk: "이 대화를 지울까요? 되돌릴 수 없어요.",
    delete: "지우기", // (9.5) the swipe action and the confirm button
    keep: "그대로 두기", // (new) the confirm sheet's other button (the app's word elsewhere)
    backToChat: "‹ 비서", // (new) the list screen's back link
    checkinTag: "체크인", // (9.5) before a check-in conversation's title
    untitled: "제목 없는 대화", // (new) a conversation the secretary has not titled yet
    search: "검색", // (new) the search box's name, as on the memos tab
    noConversations: "아직 지난 대화가 없어요.", // (new)
    noMatch: "맞는 대화가 없어요.", // (new) a search that finds nothing
    moreConversations: "더 보기", // (new) the next page, as on the memos tab
    groups: {
      today: "오늘", // (9.5)
      yesterday: "어제", // (9.5)
      thisWeek: "이번 주", // (9.5)
      month: (m: number) => `${m}월`, // (9.5) "10월"
      monthOfYear: (y: number, m: number) => `${y}년 ${m}월`, // (new) a month of another year
    },
    // SP9 9.5 퀵 칩: labels 10장 "퀵 칩" verbatim, sentences 9.5 verbatim.
    chipsLabel: "퀵 칩", // (glossary) the chip row's accessible name
    chips: {
      todo: { label: "할 일 추가", text: "할 일 추가할래요" },
      event: { label: "일정 추가", text: "일정 하나 추가할래요" },
      memo: { label: "메모하기", text: "메모 하나 남길래요" },
      today: { label: "오늘 정리해줘", text: "오늘 정리해줘" },
      checkin: { label: "체크인 하기", text: "체크인 할게요" },
      review: { label: "이번 주 돌아보기", text: "이번 주 돌아볼래요" },
      next: { label: "다음 일정 보기", text: "다음 일정 알려줘" },
    },
    openFailed: "대화를 열지 못했어요. 다시 눌러 주세요.",
    launcherBlocked: {
      unauthorized: "열쇠를 다시 넣으면 말할 수 있어요",
      rate_limited: "잠시 뒤에 말할 수 있어요",
      safe_mode: "데이터베이스 점검 뒤에 말할 수 있어요",
    },
  },

  checkin: {
    back: BACK_TODAY,
    canReply: "답장할 수 있어요",
    answeredVia: (channel: string) => `${channel}에서 답했어요`,
    answered: "답했어요",
    passed: "지나감",
    sentAt: (hhmm: string) => `${hhmm}에 보냄`,
    receivedApp: "앱 알림으로 받음",
    receivedTelegram: "텔레그램으로 받음",
    receivedBoth: "앱 알림과 텔레그램으로 받음",
    title: "체크인",
    todosHeading: "남은 할 일",
    noTodos: "남은 할 일이 없어요",
    complete: "완료",
    done: "완료",
    tomorrowLabel: (title: string) => `${title} 내일로`,
    completeLabel: (title: string) => `${title} 완료`,
    replyFailed: "답장 칸을 불러오지 못했어요",
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
    confirmExpired: "확인 시간이 지났어요. 다시 해 주세요.",
    keep: "그대로 두기",
    change: "바꾸기",
    periodsLabel: "기간",
    weekPriorities: "이번 주 우선순위",
    // A to-do the secretary added with no date, or one in a month/quarter/year tab (shown with its day).
    undated: "날짜 없는 할 일",
    periodTodos: (period: string) => `${period} 할 일`,
    periodPriorities: (period: string) => `${period} 우선순위`,
    noPriorities: "아직 정해진 우선순위가 없어요",
    noTodos: "잡힌 할 일이 없어요",
    dayHeading: (weekday: string, m: number, d: number, isToday: boolean) =>
      `${weekday} · ${m}월 ${d}일${isToday ? " · 오늘" : ""}`,
    confirmLabel: (title: string) => `${title} 확정`,
    dropLabel: (title: string) => `${title} 빼기`,
    changeDate: "날짜 바꾸기",
    editTitle: "제목 고치기",
    dateLabel: "날짜",
    dateGroup: "날짜 정하기",
    titleLabel: "제목",
    save: "저장",
    addTitle: "할 일 추가",
    addSubmit: "추가",
    areasLabel: "영역",
    dateToday: "오늘",
    dateTomorrow: "내일",
    datePick: "날짜 고르기",
    dateNone: "없음",
    noteLabel: "메모",
    close: "닫기",
  },

  activity: {
    title: "기록",
    // Off the tabs since SP9-04 (spec 9.1).
    back: BACK_MORE,
    intro: "비서와 내가 바꾼 것. 가벼운 변경은 24시간 안에 되돌릴 수 있어요.",
    undo: "되돌리기",
    undoneAt: (hhmm: string) => `${hhmm}에 되돌림`,
    undoBlocked: {
      superseded: "뒤에 또 바뀌어서 못 되돌려요",
      undo_expired: "24시간이 지났어요",
      not_undoable: "되돌릴 수 없는 변경이에요",
    },
    more: "더 보기",
    today: "오늘",
    yesterday: "어제",
    bySecretary: "비서가 한 일",
    needsConfirm: "확인이 필요해요",
    empty: "아직 기록이 없어요.",
    meta: (hhmm: string, actor: string, channel: string) => `${hhmm} · ${actor} · ${channel}`,
  },

  settings: {
    title: "설정",
    // Off the tabs since SP9-07 (spec 9.1).
    back: BACK_MORE,
    connection: "비서 연결",
    notify: "체크인 알림",
    schedule: "체크인 시간",
    pause: "쉬어 가기",
    device: "이 기기",
    about: "정보",
    disconnect: "이 기기 연결 해제",
    probeThrow: "에러 던지기",
    themeSystem: "시스템 따라",
    themeLight: "밝게",
    themeDark: "어둡게",
    checkedJustNow: "방금 확인했어요",
    checkedMinutesAgo: (n: number) => `${n}분 전에 확인했어요`,
    connectedChecked: (when: string) => `연결됨 · ${when}`,
    address: "주소",
    token: "열쇠(토큰)",
    reenter: "다시 입력",
    notifyWhere: "어디로 울릴까요",
    primaryApp: "이 앱",
    primaryTelegram: "텔레그램",
    notifyHelp: "한 곳에서만 울려요. 앱 알림이 안 가면 텔레그램으로 대신 보내요.",
    effectiveTelegram: "지금은 텔레그램으로 가요: 알림을 받을 기기가 없어요",
    devicePush: "이 기기 알림",
    pushOn: "켜짐",
    pushOff: "꺼짐",
    pushAllow: "허용하기",
    pushDenied: "알림이 꺼져 있어요. 아이폰 설정 › 알림 › 비서에서 켤 수 있어요.",
    needsHomeScreen: "홈 화면에 추가한 ‘비서’ 앱에서 알림을 켤 수 있어요.",
    pushUnsupported: "이 브라우저는 앱 알림을 받을 수 없어요.",
    pushUnavailable: "이 비서는 앱 알림을 보내도록 설정되어 있지 않아요. 텔레그램으로 받아요.",
    pushTurnOnFailed: "알림을 켜지 못했어요. 다시 해 주세요.",
    deviceLabel: "폰",
    testPush: "시험 알림 보내기",
    testNoDevices: "알림을 받을 기기가 없어요. 먼저 이 기기 알림을 허용해 주세요.",
    testSlow: "응답이 늦어요. 잠시 뒤 확인해 주세요.",
    testResult: (ok: number, failed: number) => (failed === 0 ? `${ok}대에 보냈어요` : `${ok}대에 보냈고 ${failed}대에는 안 갔어요`),
    weekdays: "평일",
    weekend: "주말",
    scheduleNote: "일요일 18:00은 주간 회고와 함께 와요. 시간은 노트북의 비서 설정에서 바꿔요.",
    pauseRow: "체크인 잠시 멈추기",
    pauseSheet: "얼마나 쉴까요",
    pauseDays: (n: number) => `${n}일`,
    pausedUntil: (when: string) => `${when}까지 쉬는 중`,
    resume: "다시 시작",
    theme: "화면",
    palette: "색감",
    palettes: { paper: "종이", ink: "잉크", forest: "숲", sea: "바다", sunset: "노을", lavender: "라벤더" },
    disconnectSummary: "이 폰에 저장된 주소, 열쇠, 받아 둔 내용이 지워져요",
    disconnectConfirm: "연결 해제",
    cancel: "그대로 두기",
    appVersion: "앱 판",
    beVersion: "비서 판",
    catalogVersion: "부품 목록 판",
    unknown: "-",
    loadFailed: "알림 설정을 불러오지 못했어요",
  },

  // SP9 9.7, 10장 "체크인 시간" (그대로)
  checkinTimes: {
    heading: "체크인 시간",
    weekdayMorning: "평일 아침",
    weekdayEvening: "평일 저녁",
    weekendMorning: "주말 아침",
    weekendEvening: "주말 저녁",
    fromToday: FROM_TODAY,
    fromTomorrow: FROM_TOMORROW,
    wakeStale: WAKE_STALE,
    reviewNote: "주말 저녁은 일요일 주간 회고 시각이기도 해요.",
  },

  // SP9b 5장, 7장 "일정 정리 알림" (그대로)
  digests: {
    heading: "일정 정리 알림",
    morning: "아침에 오늘 일정",
    night: "밤에 내일 일정",
    note: "일정이 있는 날만 보내요.",
    fromToday: FROM_TODAY,
    fromTomorrow: FROM_TOMORROW,
    wakeStale: WAKE_STALE,
  },

  // SP9 9.7, 10장 "캘린더" (그대로) + 안내 한 줄(9.7). `copied`는 10장에 없는 토스트 한 줄(복사했다는 사실만)
  calendar: {
    heading: "아이폰 캘린더에 구독",
    create: "구독 주소 만들기",
    copy: "복사",
    copied: "주소를 복사했어요",
    copyFailed: "복사하지 못했어요. 주소를 길게 눌러 복사해 주세요.",
    recreate: "주소 다시 만들기",
    recreateSummary: "이전 주소는 더 이상 갱신되지 않아요.",
    help: "아이폰 설정 → 캘린더 → 계정 → 계정 추가 → 기타 → 구독 캘린더 추가에 붙여 넣어요. 폰에서 Tailscale이 켜져 있을 때 갱신돼요.",
  },

  connect: {
    back: BACK_MORE,
    title: "노트북의 비서와 연결해요",
    intro: "한 번만 하면 돼요. 주소와 열쇠는 이 폰에만 저장되고 어디에도 올라가지 않아요.",
    ok: "연결 확인됨 · 비서가 답했어요",
    badToken: "열쇠가 맞지 않아요",
    unreachable: "주소에 닿지 않아요. 노트북과 폰의 Tailscale을 확인해 주세요.",
    urlLabel: "비서 주소",
    urlHelp: "노트북에서 tailscale serve를 켠 뒤 나오는 주소예요. 폰에서도 Tailscale이 켜져 있어야 해요.",
    tokenLabel: "열쇠",
    tokenHelp: "노트북에서 python -m my_planner gen-token으로 만든 값이에요.",
    start: "시작하기",
    startWithPush: "알림 허용하고 시작하기",
    pushLater: "알림은 나중에",
    checking: "확인하는 중",
    notHttps: "https:// 로 시작하는 주소만 쓸 수 있어요.",
    outOfRange: "이 앱에서 쓸 수 있는 주소가 아니에요. Tailscale 주소(.ts.net)를 넣어 주세요.",
    invalidUrl: "주소 모양이 맞지 않아요.",
    homeScreenGuide:
      "공유 버튼에서 ‘홈 화면에 추가’를 한 뒤, 홈 화면의 ‘비서’를 열어 연결해 주세요. 탭과 홈 화면 앱은 저장 공간이 따로라서, 여기서 넣은 값은 앱으로 넘어가지 않아요.",
  },

  // Date formats for formatKst (lib/time.ts). The Korean ones live here so time.ts has no Hangul.
  dateStyle: {
    monthDay: "M월 D일",
    monthDayTime: "M월 D일 HH:mm",
  },
  dateParts: {
    monthDay: (m: number, d: number) => `${m}월 ${d}일`,
  },

  offline: {
    lead: "노트북의 비서에 닿지 않아요.",
    snapshotAt: (hhmm: string) => `아래는 ${hhmm}에 받은 내용이고, 지금은 볼 수만 있어요.`,
    noSnapshot: "아직 받아 둔 내용이 없어요. 노트북이 켜지면 보여 드릴게요.",
    reconnect: "다시 연결",
    check: "연결 확인",
    writeLater: "비서가 다시 연결되면 할 수 있어요",
    later: "비서가 다시 연결되면 볼 수 있어요",
    catchUp: "노트북이 켜지면 지나간 체크인부터 차례로 따라잡아요.",
    chatLater: CHAT_LATER,
  },

  errors: {
    block: (code: string) => `이 부분을 불러오지 못했어요 (${code})`,
    retry: "다시 시도",
    notFound: "찾는 화면이 없어요.",
    goToday: "오늘로 가기",
    goSettings: "설정 열기",
  },

  actions: {
    failed: "저장하지 못했어요. 다시 해 주세요.",
    offline: "비서에 닿지 않아요. 연결되면 다시 해 주세요.",
    undoFailed: "되돌리지 못했어요. 다시 해 주세요.",
  },

  parts: {
    unknown: "이 화면 조각은 아직 앱이 그릴 줄 몰라요",
    todoCount: (n: number) => `할 일 ${n}개`,
    more: (n: number) => `${n}개 더`,
    less: "접기",
    draftHeading: "할 일 초안",
    draftHint: "확정 전까지 초안이에요",
    dropChecked: "고른 것 빼기",
    confirmCount: (n: number) => `${n}개 확정`,
    scoreLow: "많이 지침",
    scoreHigh: "아주 좋음",
    notePlaceholder: "메모 (선택)",
    noteLabel: "컨디션 메모",
    ladderNow: "지금",
    ladderFuture: "5년 뒤",
    ladderScore: (n: number) => `${n}점`,
    ladderPrompt: (field: "now" | "future") => (field === "now" ? "지금의 나는 몇 점인가요?" : "5년 뒤의 나는 몇 점일까요?"),
    areaLabel: (area: string) => `${area} 점수`,
    previous: (n: number) => `지난번 ${n}`,
    save: "저장",
    milestoneHeading: "사건 초안",
    milestoneCount: (n: number) => `사건 초안 ${n}개`,
    chapterHeading: "챕터 초안",
    chapterCount: (n: number) => `챕터 초안 ${n}개`,
    drop: "빼기",
    confirmOne: "확정",
    yearMonth: (y: number, m: number) => `${y}년 ${m}월`,
    period: (from: string, to: string | null) => (to ? `${from} ~ ${to}` : `${from} ~ 지금`),
    confirmGone: "이미 지나간 확인이에요",
    checkLabel: (title: string) => `${title} 체크`,
    // SP6 appendix A: the ten parts and CheckRow (Dahun to confirm). The rest of appendix A is G-A2.
    weekdays: ["일", "월", "화", "수", "목", "금", "토"],
    dayLabel: (m: number, d: number, w: string) => `${m}월 ${d}일 (${w})`,
    today: "오늘",
    tomorrow: "내일",
    yesterday: "어제",
    noTodos: "보여 줄 할 일이 없어요",
    dropped: "뺌",
    changedBySecretary: "비서가 바꿈",
    trendAria: {
      up: (t: string) => `지난번보다 올라감 ${t}`,
      down: (t: string) => `지난번보다 내려감 ${t}`,
      same: "지난번과 같음",
    },
    progressAria: (l: string, n: number, m: number) => `${l} ${n}/${m}`,
    tagsLabel: "태그",
    // SP6 appendix A, the chat cards (G-A2, Dahun to confirm).
    thisWeek: "이번 주",
    nextWeek: "다음 주",
    lastWeek: "지난주",
    weekRange: (a: string, b: string) => `${a} ~ ${b}`,
    monthDay: (m: number, d: number) => `${m}월 ${d}일`,
    dayHead: (d: number, w: string) => `${d}일 ${w}`,
    dayHeadToday: " · 오늘",
    relativeDay: (rel: string, day: string) => `${rel} · ${day}`,
    otherDay: "다른 날로 할게요",
    alreadySettled: "이미 정리된 할 일이에요",
    noDate: "날짜 없음",
    changeChip: {
      added: "추가",
      moved: "옮김",
      completed: "완료",
      reopened: "다시 엶",
      dropped: "뺌",
      updated: "고침",
      confirmed: "확정",
    },
    prevTitle: (t: string) => `이전 제목: ${t}`,
    editedOnly: "내용을 고쳤어요",
    confirmedDraft: "초안을 확정했어요",
    arrow: " → ",
    changeAria: (a: string, b: string) => `이전 ${a}, 지금 ${b}`,
    resultCount: (n: number) => `바뀐 할 일 ${n}개`,
    outsideHead: {
      moved: "기간 밖으로 옮긴 것",
      dropped: "뺀 것",
      noDate: "날짜 없는 것",
    },
    openTodos: "할 일 화면에서 보기",
    openActivity: "기록에서 보기",
    periodFailed: "할 일을 불러오지 못했어요",
  },

  // SP7 6.1, 6.2, appendix A (Dahun confirmed). Counts of what was done only: no ratio, no bar,
  // nothing about what is left.
  habits: {
    heading: "습관",
    manage: "관리",
    todayLine: "오늘 습관",
    addRow: "습관 추가하기",
    empty: "챙기고 싶은 습관을 더해 보세요. 매일 하는 것도, 주 몇 번 하는 것도 돼요.",
    weekOfTarget: (n: number, target: number) => `이번 주 ${n}번 · 목표 ${target}번`,
    weekMet: "이번 주 목표만큼 했어요",
    week: (n: number) => `이번 주 ${n}번`,
    lastWeek: (n: number) => `지난주 ${n}번`,
    weekOf: (m: number, d: number, n: number) => `${m}월 ${d}일 주 ${n}번`,
    // 6.2 habits screen and its sheets. Back is "‹ 더보기" since SP9 9.1.
    back: BACK_MORE,
    add: "습관 추가",
    editTitle: "습관 고치기",
    active: "챙기는 습관",
    paused: "쉬는 습관",
    archived: "그만둔 습관",
    resume: "다시 시작",
    resumeLabel: (title: string) => `${title} 다시 시작`,
    edit: "고치기",
    pause: "쉬어 가기",
    archive: "그만두기",
    daily: "매일",
    weekly: "주 N회",
    weeklyN: (n: number) => `주 ${n}회`,
    detailMeta: (area: string, cadence: string) => `${area} · ${cadence}`,
    gridLabel: "지난 4주",
    titleLabel: "제목",
    areaLabel: "영역",
    cadenceLabel: "주기",
    targetLabel: "주 몇 회",
    addSubmit: "추가",
    save: "저장",
    close: "닫기",
  },

  areas: {
    career: "커리어",
    finance: "경제",
    health: "건강",
    relationships: "관계",
    learning: "배움",
    quality_of_life: "삶의 질",
  } satisfies Record<Todo["areas"][number], string>,

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
    scheduler: "정해진 시각",
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

const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];

/** "10월 24일 (토)": the date head over a day's moments (SP8 appendix A). `date` is a calendar day, "YYYY-MM-DD". */
export function momentDay(date: string): string {
  const [y, m, d] = date.split("-").map(Number);
  return `${m}월 ${d}일 (${WEEKDAYS[new Date(Date.UTC(y, m - 1, d)).getUTCDay()]})`;
}

/** The grey line at the right of a habit row (SP7 6.1). The app works out "met"; it earns nothing. */
export function habitMeta(h: Pick<Habit, "kind" | "target_per_week" | "week_count">): string {
  if (h.kind === "weekly" && h.target_per_week !== null) {
    return h.week_count >= h.target_per_week ? copy.habits.weekMet : copy.habits.weekOfTarget(h.week_count, h.target_per_week);
  }
  return copy.habits.week(h.week_count);
}
