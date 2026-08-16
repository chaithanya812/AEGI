/** The architecture, lighting up as the run proceeds.
 *
 *  Node states are driven by the actual trace events, not by a timer. If a stage did not
 *  run — because the rig switched it off, or it failed — its node stays unlit. A diagram
 *  that animates the happy path regardless of what happened would be decoration, and this
 *  product is specifically about not doing that.
 */

import type { TraceEvent } from "../api/types";

interface Node {
  id: string;
  label: string;
  module: string;
  x: number;
  y: number;
  w?: number;
  /** Trace stages that light this node. */
  stages: string[];
}

const W = 74;
const H = 26;

const NODES: Node[] = [
  { id: "in", label: "INPUT", module: "MP-01", x: 8, y: 6, stages: ["gateway.accept"] },
  { id: "llm", label: "MODEL", module: "MP-02", x: 8, y: 48, stages: ["model.generate"] },
  { id: "claims", label: "CLAIMS", module: "MP-04/05", x: 8, y: 90, stages: ["claims.extract"] },
  { id: "rag", label: "RETRIEVE", module: "MP-06/44", x: 8, y: 132, stages: ["evidence.retrieve"] },
  { id: "temporal", label: "TEMPORAL", module: "MP-12", x: 128, y: 62, stages: ["verdict.assess"] },
  { id: "citation", label: "CITATION", module: "MP-11", x: 128, y: 104, stages: ["verdict.assess"] },
  { id: "judge", label: "ENTAILMENT", module: "MP-09", x: 128, y: 146, stages: ["verdict.assess"] },
  {
    id: "contra",
    label: "CONTRADICT",
    module: "MP-10",
    x: 128,
    y: 188,
    stages: ["contradiction.detect"],
  },
  { id: "score", label: "LEDGER", module: "MP-13", x: 248, y: 104, stages: ["reliability.score"] },
  { id: "certain", label: "CERTAINTY", module: "new", x: 248, y: 146, stages: ["certainty.compare"] },
  { id: "decide", label: "DECISION", module: "MP-15", x: 368, y: 104, stages: ["decision.apply"] },
  { id: "cert", label: "SIGNED", module: "MP-33", x: 368, y: 146, stages: ["certificate.sign"] },
];

const EDGES: [string, string][] = [
  ["in", "llm"],
  ["llm", "claims"],
  ["claims", "rag"],
  ["rag", "temporal"],
  ["rag", "citation"],
  ["rag", "judge"],
  ["rag", "contra"],
  ["temporal", "score"],
  ["citation", "score"],
  ["judge", "score"],
  ["contra", "score"],
  ["score", "certain"],
  ["score", "decide"],
  ["certain", "decide"],
  ["decide", "cert"],
];

type State = "off" | "true" | "done";

function nodeState(node: Node, events: TraceEvent[], running: boolean): State {
  const seen = events.some((e) => node.stages.includes(e.stage));
  if (!seen) return "off";
  if (running) {
    const last = events[events.length - 1];
    if (last && node.stages.includes(last.stage)) return "true";
  }
  return "done";
}

export function PipelineGraph({
  events,
  running,
  layers,
}: {
  events: TraceEvent[];
  running: boolean;
  layers: Record<string, boolean>;
}) {
  const disabled = new Set<string>();
  if (!layers.temporal) disabled.add("temporal");
  if (!layers.citation) disabled.add("citation");
  if (!layers.judge) disabled.add("judge");
  if (!layers.contradiction) disabled.add("contra");
  if (!layers.retrieval) disabled.add("rag");

  const states = new Map<string, State>();
  for (const node of NODES) {
    states.set(node.id, disabled.has(node.id) ? "off" : nodeState(node, events, running));
  }

  const byId = new Map(NODES.map((n) => [n.id, n]));

  return (
    <div className="graph">
      <svg viewBox="0 0 460 226" role="img" aria-label="Verification pipeline, stages lit as they run">
        {EDGES.map(([from, to]) => {
          const a = byId.get(from)!;
          const b = byId.get(to)!;
          const on = states.get(from) === "done" && states.get(to) !== "off";
          const x1 = a.x + (a.w ?? W);
          const y1 = a.y + H / 2;
          const x2 = b.x;
          const y2 = b.y + H / 2;
          const path =
            a.x === b.x
              ? `M ${a.x + (a.w ?? W) / 2} ${a.y + H} L ${b.x + (b.w ?? W) / 2} ${b.y}`
              : `M ${x1} ${y1} C ${x1 + 22} ${y1}, ${x2 - 22} ${y2}, ${x2} ${y2}`;
          return (
            <path key={`${from}-${to}`} className="gedge" data-on={on ? "true" : undefined} d={path} />
          );
        })}

        {NODES.map((node) => {
          const state = states.get(node.id)!;
          const struck = disabled.has(node.id);
          return (
            <g key={node.id}>
              <rect
                className="gnode"
                data-on={state === "off" ? undefined : state}
                x={node.x}
                y={node.y}
                width={node.w ?? W}
                height={H}
                strokeDasharray={struck ? "3 2" : undefined}
              />
              <text
                className="glabel"
                data-on={state === "off" ? undefined : state}
                x={node.x + (node.w ?? W) / 2}
                y={node.y + 12}
                textAnchor="middle"
              >
                {node.label}
              </text>
              <text
                className="gmod"
                data-on={state === "done" ? "done" : undefined}
                x={node.x + (node.w ?? W) / 2}
                y={node.y + 21}
                textAnchor="middle"
              >
                {struck ? "off" : node.module}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
