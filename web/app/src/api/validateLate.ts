import { Validator, type Schema } from "@cfworker/json-schema";
import { type ApiResult, apiFetch, type FetchOpts } from "./client";
import late from "./schema.late.json";
import { openObjects } from "./validate";

// Shape checks for the models in scripts/late-models.json (SP15). Their schemas live in
// schema.late.json, not schema.json, so they stay out of the first screen's bundle: import this
// file only from the chat and page chunks, never from api/client.ts, api/validate.ts, _app, lib/*,
// ui/registry or the connection provider (schemaSplit.test.ts checks those).
export type LateModelName = keyof typeof late.models;

const validators = new Map<LateModelName, Validator>();

function validatorFor(model: LateModelName): Validator {
  let v = validators.get(model);
  if (!v) {
    v = new Validator(openObjects(late.models[model]) as Schema, "2020-12", true);
    validators.set(model, v);
  }
  return v;
}

export function validateLateModel(model: LateModelName, value: unknown): boolean {
  return validatorFor(model).validate(value).valid;
}

/** `GET` like `apiGet`, checked against a late model: a 200 of the wrong shape is `error` "shape". */
export async function apiGetLate<T>(path: string, model: LateModelName, opts: FetchOpts = {}): Promise<ApiResult<T>> {
  const r = await apiFetch<T>("GET", path, opts);
  if (r.kind === "ok" && !validateLateModel(model, r.data)) return { kind: "error", status: 200, code: "shape" };
  return r;
}
