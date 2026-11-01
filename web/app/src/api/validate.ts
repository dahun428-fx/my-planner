import { Validator, type Schema } from "@cfworker/json-schema";
import schema from "./schema.json";

// Response shape checks. @cfworker/json-schema interprets schemas without eval/new Function,
// so it runs under CSP script-src 'self' (no 'unsafe-eval').
export type ModelName = keyof typeof schema.models;

const validators = new Map<ModelName, Validator>();

// The BE contract says adding a field is not breaking and clients ignore unknown fields. The
// generated schema closes every object, so that is opened here once, for every model and $def.
export function openObjects(node: unknown): unknown {
  if (Array.isArray(node)) return node.map(openObjects);
  if (!node || typeof node !== "object") return node;
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(node)) {
    if (k === "additionalProperties" && v === false) continue;
    out[k] = openObjects(v);
  }
  return out;
}

function validatorFor(model: ModelName): Validator {
  let v = validators.get(model);
  if (!v) {
    v = new Validator(openObjects(schema.models[model]) as Schema, "2020-12", true);
    validators.set(model, v);
  }
  return v;
}

export function validateModel(model: ModelName, value: unknown): boolean {
  return validatorFor(model).validate(value).valid;
}
