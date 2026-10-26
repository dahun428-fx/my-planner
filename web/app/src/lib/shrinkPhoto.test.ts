import { afterEach, describe, expect, it, vi } from "vitest";
import { PhotoUnopenable, type ShrinkDeps, shrinkPhoto } from "./shrinkPhoto";

// SP10 12장 앱: 줄이기 (resizeWidth 사용, 긴 변 2,048·400, 5MB 재시도, 비트맵은 가짜).

interface Drawn {
  width: number;
  height: number;
  quality: number;
}

function fakeBitmap(width: number, height: number) {
  return { width, height, close: vi.fn() } as unknown as ImageBitmap;
}

/** A decoder whose bitmap honours resizeWidth / resizeHeight the way the browser does (aspect kept). */
function fakeDeps(width: number, height: number, sizes: (d: Drawn) => number = () => 1000) {
  const drawn: Drawn[] = [];
  const asked: ImageBitmapOptions[] = [];
  let made: ImageBitmap | null = null;
  const deps: ShrinkDeps = {
    size: async () => ({ width, height }),
    bitmap: async (_f, opts) => {
      asked.push(opts);
      let w = width;
      let h = height;
      if (opts.resizeWidth) {
        h = Math.round((height * opts.resizeWidth) / width);
        w = opts.resizeWidth;
      } else if (opts.resizeHeight) {
        w = Math.round((width * opts.resizeHeight) / height);
        h = opts.resizeHeight;
      }
      made = fakeBitmap(w, h);
      return made;
    },
    jpeg: async (_b, w, h, quality) => {
      const d = { width: w, height: h, quality };
      drawn.push(d);
      return new Blob([new Uint8Array(sizes(d))], { type: "image/jpeg" });
    },
  };
  return { deps, drawn, asked, bitmap: () => made };
}

const file = () => new File([new Uint8Array(10)], "IMG_0001.HEIC", { type: "image/heic" });

describe("shrinkPhoto (spec 7.2)", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("a wide 48 MP photo decodes with resizeWidth 2048, then a 400px small one, from one bitmap", async () => {
    const f = fakeDeps(8064, 6048);
    const out = await shrinkPhoto(file(), f.deps);
    expect(f.asked).toEqual([{ imageOrientation: "from-image", resizeQuality: "high", resizeWidth: 2048 }]);
    expect(f.drawn).toEqual([
      { width: 2048, height: 1536, quality: 0.85 },
      { width: 400, height: 300, quality: 0.8 },
    ]);
    expect(out.image.type).toBe("image/jpeg");
    expect(out.thumb.type).toBe("image/jpeg");
    expect(f.bitmap()!.close).toHaveBeenCalled();
  });

  it("a tall photo uses resizeHeight (its long side)", async () => {
    const f = fakeDeps(3024, 4032);
    await shrinkPhoto(file(), f.deps);
    expect(f.asked[0]).toEqual({ imageOrientation: "from-image", resizeQuality: "high", resizeHeight: 2048 });
    expect(f.drawn[0]).toMatchObject({ width: 1536, height: 2048 });
    expect(f.drawn[1]).toMatchObject({ width: 300, height: 400 });
  });

  it("a photo already small is not made larger", async () => {
    const f = fakeDeps(1200, 300);
    await shrinkPhoto(file(), f.deps);
    expect(f.asked[0]).not.toHaveProperty("resizeWidth");
    expect(f.asked[0]).not.toHaveProperty("resizeHeight");
    expect(f.drawn[0]).toMatchObject({ width: 1200, height: 300 });
    expect(f.drawn[1]).toMatchObject({ width: 400, height: 100 });
  });

  it("over 5,000,000 bytes at 0.85 it is drawn once more at 0.7", async () => {
    const f = fakeDeps(4000, 3000, (d) => (d.quality === 0.85 ? 5_000_001 : 4_000_000));
    const out = await shrinkPhoto(file(), f.deps);
    expect(f.drawn.map((d) => d.quality)).toEqual([0.85, 0.7, 0.8]);
    expect(out.image.size).toBe(4_000_000);
  });

  it("exactly 5,000,000 bytes is kept", async () => {
    const f = fakeDeps(4000, 3000, () => 5_000_000);
    await shrinkPhoto(file(), f.deps);
    expect(f.drawn.map((d) => d.quality)).toEqual([0.85, 0.8]);
  });

  it("a photo that cannot be decoded throws PhotoUnopenable", async () => {
    const f = fakeDeps(4000, 3000);
    f.deps.bitmap = async () => {
      throw new DOMException("bad", "InvalidStateError");
    };
    await expect(shrinkPhoto(file(), f.deps)).rejects.toBeInstanceOf(PhotoUnopenable);
    f.deps.size = async () => ({ width: 0, height: 0 });
    await expect(shrinkPhoto(file(), f.deps)).rejects.toBeInstanceOf(PhotoUnopenable);
  });

  it("the browser path calls createImageBitmap with the resize and draws on a canvas as JPEG", async () => {
    class FakeImage {
      naturalWidth = 6000;
      naturalHeight = 4000;
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      set src(_v: string) {
        queueMicrotask(() => this.onload?.());
      }
    }
    vi.stubGlobal("Image", FakeImage);
    const cib = vi.fn(async (_f: Blob, o: ImageBitmapOptions) => fakeBitmap(o.resizeWidth ?? 6000, Math.round(((o.resizeWidth ?? 6000) * 2) / 3)));
    vi.stubGlobal("createImageBitmap", cib);
    const drawImage = vi.fn();
    const toBlob = vi.fn(function (this: HTMLCanvasElement, cb: BlobCallback, type?: string, _quality?: number) {
      cb(new Blob([new Uint8Array(this.width)], { type }));
    });
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ drawImage } as unknown as CanvasRenderingContext2D);
    vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation(toBlob);
    const out = await shrinkPhoto(file());
    expect(cib).toHaveBeenCalledWith(expect.any(File), { imageOrientation: "from-image", resizeQuality: "high", resizeWidth: 2048 });
    expect(drawImage.mock.calls.map((c) => [c[3], c[4]])).toEqual([
      [2048, 1365],
      [400, 267],
    ]);
    expect(toBlob.mock.calls.map((c) => [c[1], c[2]])).toEqual([
      ["image/jpeg", 0.85],
      ["image/jpeg", 0.8],
    ]);
    expect(out.image.size).toBe(2048);
    vi.restoreAllMocks();
  });
});
