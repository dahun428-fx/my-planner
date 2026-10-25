// The `text` part's markdown (SP6 spec 5.3.2): `**…**` is strong and `\n` breaks the line. Nothing
// else is read: unpaired `**`, `#`, `[]()`, `<…>`, backticks, `*` and `_` stay as typed. The result
// goes into React text nodes, never into HTML.
export type MiniLine = { text: string; strong: boolean }[];

const STRONG = /\*\*([^*\n]+?)\*\*/g;

export function parseMiniMd(md: string): MiniLine[] {
  return md.split("\n").map((line) => {
    const out: MiniLine = [];
    let at = 0;
    for (const m of line.matchAll(STRONG)) {
      if (m.index > at) out.push({ text: line.slice(at, m.index), strong: false });
      out.push({ text: m[1], strong: true });
      at = m.index + m[0].length;
    }
    if (at < line.length) out.push({ text: line.slice(at), strong: false });
    return out;
  });
}
