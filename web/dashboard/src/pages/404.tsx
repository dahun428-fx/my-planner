import Link from "next/link";

// Next's default 404 carries inline styles, which style-src 'self' blocks (check-csp).
export default function NotFound() {
  return (
    <>
      <h1>없는 화면이에요</h1>
      <p>
        <Link href="/">비서 상태로 가기</Link>
      </p>
    </>
  );
}
