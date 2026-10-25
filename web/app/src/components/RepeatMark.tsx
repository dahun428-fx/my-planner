import { copy } from "../lib/copy";

// SP9 9.2·9.8: 반복 일정 줄의 작은 반복 표시(돌아가는 두 화살표). 24px 판, 선 1.75, 끝 둥글게(SP8 픽토그램 규칙).
// 보이는 크기는 CSS(`className`)가 정한다. 읽는 이름은 "반복".
export function RepeatMark({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      role="img"
      aria-label={copy.schedule.repeating}
      focusable="false"
    >
      <path d="M4.5 11a7.5 7.5 0 0 1 13-4.5L19.5 8.5" />
      <path d="M19.5 4v4.5H15" />
      <path d="M19.5 13a7.5 7.5 0 0 1-13 4.5L4.5 15.5" />
      <path d="M4.5 20v-4.5H9" />
    </svg>
  );
}
