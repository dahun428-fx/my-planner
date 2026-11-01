import { copy } from "./copy";

export type AgentName = keyof typeof copy.agentNames;
export interface AgentNote {
  agent: AgentName;
  text: string;
}

const PREFIXES = (Object.keys(copy.agentNames) as AgentName[]).map((agent) => ({ agent, prefix: `${copy.agentNames[agent]}: ` }));

// SP14 10장: the brief's observation lines ("운동메이트: …", "라이프 매니저: …" at a line's start, anywhere
// in the text: the brain may keep one in place, the harness adds others at the end) come out in order;
// the rest stays the Markdown body, its trailing blank lines dropped.
export function splitAgentNotes(text: string): { body: string; notes: AgentNote[] } {
  const notes: AgentNote[] = [];
  const kept: string[] = [];
  for (const line of text.split("\n")) {
    const hit = PREFIXES.find((p) => line.startsWith(p.prefix) && line.slice(p.prefix.length).trim() !== "");
    if (hit) notes.push({ agent: hit.agent, text: line.slice(hit.prefix.length).trim() });
    else kept.push(line);
  }
  if (notes.length === 0) return { body: text, notes };
  while (kept.length > 0 && kept[kept.length - 1].trim() === "") kept.pop();
  return { body: kept.join("\n"), notes };
}
