import { http, HttpResponse } from "msw";
import { vi } from "vitest";
import type { PartContext } from "../ui/types";
import { BASE, server } from "./server";

export function makeCtx(over: Partial<PartContext> = {}): PartContext & { onAfterAction: ReturnType<typeof vi.fn> } {
  return { where: "chat", readOnly: false, onAfterAction: vi.fn(), ...over } as PartContext & { onAfterAction: ReturnType<typeof vi.fn> };
}

/** Answers POST /actions and returns every request body it saw. */
export function serveActions(answer?: (body: Record<string, unknown>) => Response | Promise<Response>) {
  const bodies: Record<string, unknown>[] = [];
  server.use(
    http.post(`${BASE}/actions`, async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      bodies.push(body);
      return answer ? answer(body) : applied();
    }),
  );
  return bodies;
}

export const applied = () =>
  HttpResponse.json({ status: "applied", activity_id: 901, undo_id: 901, result: {}, confirmation: "✓ 처리했어요" });
