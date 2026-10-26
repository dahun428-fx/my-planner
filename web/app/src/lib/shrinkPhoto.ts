// SP10 7.2: a picked photo is decoded already shrunk (createImageBitmap resize, so a 24 or 48 MP
// photo never needs a full-size canvas, which iOS limits), drawn on a canvas and sent as JPEG.
// Drawing again turns HEIC into JPEG and leaves EXIF (the place too) behind (6장).

export const LONG_SIDE = 2048;
export const THUMB_SIDE = 400;
export const MAX_IMAGE_BYTES = 5_000_000;
const QUALITY = 0.85;
const QUALITY_RETRY = 0.7;
const THUMB_QUALITY = 0.8;

export class PhotoUnopenable extends Error {
  constructor() {
    super("photo_unopenable");
  }
}

/** The browser parts shrinkPhoto uses; tests hand in fakes (there is no image decoder in jsdom). */
export interface ShrinkDeps {
  /** The photo's size as shown (EXIF orientation applied), read without drawing it. */
  size(file: Blob): Promise<{ width: number; height: number }>;
  bitmap(file: Blob, opts: ImageBitmapOptions): Promise<ImageBitmap>;
  /** Draws `bitmap` at `width`×`height` and gives it back as a JPEG of that quality. */
  jpeg(bitmap: ImageBitmap, width: number, height: number, quality: number): Promise<Blob>;
}

function sizeOf(file: Blob): Promise<{ width: number; height: number }> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      resolve({ width: img.naturalWidth, height: img.naturalHeight });
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new PhotoUnopenable());
    };
    img.src = url;
  });
}

function jpegOf(bitmap: ImageBitmap, width: number, height: number, quality: number): Promise<Blob> {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) return Promise.reject(new PhotoUnopenable());
  ctx.drawImage(bitmap, 0, 0, width, height);
  return new Promise((resolve, reject) => {
    canvas.toBlob((b) => (b ? resolve(b) : reject(new PhotoUnopenable())), "image/jpeg", quality);
  });
}

const browserDeps: ShrinkDeps = {
  size: sizeOf,
  bitmap: (file, opts) => createImageBitmap(file, opts),
  jpeg: jpegOf,
};

/** Fits `w`×`h` inside a `side` long side, never larger than it was. */
function fit(w: number, h: number, side: number): { width: number; height: number } {
  const long = Math.max(w, h);
  if (long <= side) return { width: w, height: h };
  const k = side / long;
  return { width: Math.max(1, Math.round(w * k)), height: Math.max(1, Math.round(h * k)) };
}

/**
 * The photo to send (long side 2,048 or less, JPEG 0.85, 0.7 once more if over 5,000,000 bytes) and
 * its small one (long side 400, JPEG 0.8), from one bitmap. Throws PhotoUnopenable when it cannot
 * be read ("이 사진은 열 수 없어요.").
 */
export async function shrinkPhoto(file: File, deps: ShrinkDeps = browserDeps): Promise<{ image: Blob; thumb: Blob }> {
  let bitmap: ImageBitmap | null = null;
  try {
    const { width, height } = await deps.size(file);
    if (!(width > 0 && height > 0)) throw new PhotoUnopenable();
    const opts: ImageBitmapOptions = { imageOrientation: "from-image", resizeQuality: "high" };
    if (Math.max(width, height) > LONG_SIDE) {
      if (width >= height) opts.resizeWidth = LONG_SIDE;
      else opts.resizeHeight = LONG_SIDE;
    }
    bitmap = await deps.bitmap(file, opts);
    const big = fit(bitmap.width, bitmap.height, LONG_SIDE);
    let image = await deps.jpeg(bitmap, big.width, big.height, QUALITY);
    if (image.size > MAX_IMAGE_BYTES) image = await deps.jpeg(bitmap, big.width, big.height, QUALITY_RETRY);
    const small = fit(bitmap.width, bitmap.height, THUMB_SIDE);
    const thumb = await deps.jpeg(bitmap, small.width, small.height, THUMB_QUALITY);
    return { image, thumb };
  } catch (e) {
    throw e instanceof PhotoUnopenable ? e : new PhotoUnopenable();
  } finally {
    bitmap?.close();
  }
}
