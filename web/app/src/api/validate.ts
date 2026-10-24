import { Validator, type Schema } from "@cfworker/json-schema";
import schema from "./schema.json";

// Response shape checks. @cfworker/json-schema interprets schemas without eval/new Function,
// so it runs under CSP script-src 'self' (no 'unsafe-eval').
export type ModelName = keyof typeof schema.models;

const validators = new Map<ModelName, Validator>();

function validatorFor(model: ModelName): Validator {
  let v = validators.get(model);
  if (!v) {
    v = new Validator(schema.models[model] as unknown as Schema, "2020-12", true);
    validators.set(model, v);
  }
  return v;
}

export function validateModel(model: ModelName, value: unknown): boolean {
  return validatorFor(model).validate(value).valid;
}
