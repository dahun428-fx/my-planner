#!/usr/bin/env node
// App icons (spec 11장): a black square with one white "비", no gradient. Writes
// public/icons/{icon-192,icon-512,apple-touch-icon}.png with @napi-rs/canvas (dev dependency).
// Run `npm run icons` when the mark changes; the PNGs are committed.
import { mkdirSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createCanvas, GlobalFonts } from "@napi-rs/canvas";

const MARK = "비"; // 비
const SIZES = { "icon-192.png": 192, "icon-512.png": 512, "apple-touch-icon.png": 180 };
// Fonts with Hangul, first found wins (macOS, Noto, the Linux CI image).
const FONTS = ["Apple SD Gothic Neo", "Noto Sans KR", "Noto Sans CJK KR", "WenQuanYi Zen Hei", "NanumGothic"];

export function pickFont() {
  const have = new Set(GlobalFonts.families.map((f) => f.family));
  const font = FONTS.find((f) => have.has(f));
  if (!font) throw new Error(`no Hangul font found (looked for: ${FONTS.join(", ")})`);
  return font;
}

export function drawIcon(size, font) {
  const canvas = createCanvas(size, size);
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#000000";
  ctx.fillRect(0, 0, size, size);
  ctx.fillStyle = "#ffffff";
  ctx.textAlign = "center";
  ctx.textBaseline = "alphabetic";
  ctx.font = `700 ${Math.round(size * 0.56)}px "${font}"`;
  // Centre the glyph's ink box, not the em box.
  const m = ctx.measureText(MARK);
  ctx.fillText(MARK, size / 2, size / 2 + (m.actualBoundingBoxAscent - m.actualBoundingBoxDescent) / 2);
  return canvas.toBuffer("image/png");
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const out = resolve(fileURLToPath(import.meta.url), "../../public/icons");
  mkdirSync(out, { recursive: true });
  const font = pickFont();
  for (const [name, size] of Object.entries(SIZES)) {
    writeFileSync(join(out, name), drawIcon(size, font));
    console.log(`icons: ${name} ${size}x${size} (${font})`);
  }
}
