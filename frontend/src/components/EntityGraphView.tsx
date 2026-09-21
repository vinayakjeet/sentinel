import { useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D, { type ForceGraphMethods } from "react-force-graph-2d";
import type { EntityGraph, GraphNode } from "../api/types";

// Red is reserved for fraud, so entity types use cool, muted hues.
const TYPE_COLOUR: Record<GraphNode["type"], string> = {
  application: "#9db8e6",
  device: "#5fb4c9",
  email: "#8a8fd6",
  phone: "#5ea98f",
  ip: "#b79ad1",
  address: "#c2a878",
};
const FRAUD = "#f0565f";

interface N extends GraphNode { x?: number; y?: number }
interface L { source: string | N; target: string | N }

export function EntityGraphView({ graph }: { graph: EntityGraph }) {
  const box = useRef<HTMLDivElement>(null);
  const fg = useRef<ForceGraphMethods<N, L> | undefined>(undefined);
  const [size, setSize] = useState({ w: 600, h: 420 });
  const [hover, setHover] = useState<N | null>(null);
  const centre = `app:${graph.application_id}`;

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    setSize({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);

  // The library mutates the objects it is given, so hand it copies.
  const data = useMemo(
    () => ({ nodes: graph.nodes.map((n) => ({ ...n })) as N[], links: graph.edges.map((e) => ({ ...e })) as L[] }),
    [graph],
  );
  const fraudCount = graph.nodes.filter((n) => n.fraud).length;

  return (
    <div>
      <div ref={box} className="relative h-[420px] overflow-hidden rounded border border-ink-800 bg-ink-950">
        <ForceGraph2D<N, L>
          ref={fg}
          width={size.w}
          height={size.h}
          graphData={data}
          backgroundColor="#070c17"
          nodeRelSize={4}
          linkColor={() => "rgba(107,124,163,0.35)"}
          linkWidth={0.8}
          cooldownTicks={140}
          onEngineStop={() => fg.current?.zoomToFit(400, 36)}
          onNodeHover={(n) => setHover((n as N) ?? null)}
          nodeLabel={(n) => `${n.type}: ${n.label}${n.fraud ? " (linked to confirmed fraud)" : ""}`}
          nodeCanvasObject={(node, ctx, scale) => {
            const n = node as N;
            const isCentre = n.id === centre;
            const r = isCentre ? 7 : n.type === "application" ? 3.6 : 4.6;
            const x = n.x ?? 0;
            const y = n.y ?? 0;
            ctx.beginPath();
            if (n.type === "application") ctx.arc(x, y, r, 0, 2 * Math.PI);
            else ctx.rect(x - r, y - r, r * 2, r * 2); // entities are squares, applications are circles
            ctx.fillStyle = n.fraud ? FRAUD : TYPE_COLOUR[n.type];
            ctx.fill();
            if (isCentre) {
              ctx.lineWidth = 2 / scale;
              ctx.strokeStyle = "#eef2fa";
              ctx.stroke();
            } else if (n.fraud) {
              ctx.lineWidth = 1.4 / scale;
              ctx.strokeStyle = "#ffd0d3";
              ctx.stroke();
            }
            if (isCentre || hover?.id === n.id) {
              ctx.font = `${11 / scale}px "IBM Plex Sans", sans-serif`;
              ctx.textAlign = "center";
              ctx.textBaseline = "top";
              ctx.fillStyle = "#eef2fa";
              ctx.fillText(isCentre ? `${n.label} (this case)` : n.label, x, y + r + 2 / scale);
            }
          }}
          nodePointerAreaPaint={(node, colour, ctx) => {
            const n = node as N;
            ctx.fillStyle = colour;
            ctx.beginPath();
            ctx.arc(n.x ?? 0, n.y ?? 0, 8, 0, 2 * Math.PI);
            ctx.fill();
          }}
        />
        {graph.nodes.length <= 1 && (
          <p className="absolute inset-0 grid place-items-center px-6 text-center text-xs text-ink-300">
            No other applications share a device, email, phone, address or IP with this one.
          </p>
        )}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-2xs text-ink-300">
        <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-[#9db8e6]" aria-hidden />Application</span>
        {(["device", "email", "phone", "ip", "address"] as const).map((t) => (
          <span key={t} className="flex items-center gap-1.5">
            <span className="h-2 w-2" style={{ background: TYPE_COLOUR[t] }} aria-hidden />{t}
          </span>
        ))}
        <span className="flex items-center gap-1.5"><span className="h-2 w-2 bg-band-decline" aria-hidden />Linked to confirmed fraud ({fraudCount})</span>
        <span className="ml-auto text-ink-400">
          {graph.nodes.length} nodes, {graph.edges.length} links{graph.truncated ? " (capped at 200 nodes)" : ""}
        </span>
      </div>
    </div>
  );
}
