import qrcode from "qrcode-generator";
import { useMemo } from "react";
import styles from "./Qr.module.css";

// Device pairing spec 5.2: the QR is drawn here in the browser (the code never goes to a QR service).
// One SVG path of dark modules on a light quiet zone; the colours come from the stylesheet, since
// scanners want dark on light whatever the theme.
export function Qr({ text, label }: { text: string; label: string }) {
  const { size, d } = useMemo(() => {
    const qr = qrcode(0, "M");
    qr.addData(text);
    qr.make();
    const n = qr.getModuleCount();
    let path = "";
    for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) if (qr.isDark(r, c)) path += `M${c} ${r}h1v1h-1z`;
    return { size: n, d: path };
  }, [text]);
  const q = 4; // quiet zone, in modules
  return (
    <svg className={styles.qr} viewBox={`${-q} ${-q} ${size + 2 * q} ${size + 2 * q}`} role="img" aria-label={label}>
      <path d={d} fill="currentColor" />
    </svg>
  );
}
