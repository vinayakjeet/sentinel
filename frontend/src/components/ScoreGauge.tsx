import type { Band, Thresholds } from "../api/types";
import { BAND } from "../lib/format";

const W = 280;
const H = 168;
const CX = W / 2;
const CY = 140;
const R = 108;

// Score 0 sits at the left end of the dial and 1000 at the right end of a half circle.
const point = (score: number, r = R) => {
  const t = Math.PI * (1 - Math.min(1000, Math.max(0, score)) / 1000);
  return { x: CX + r * Math.cos(t), y: CY - r * Math.sin(t) };
};
const arc = (from: number, to: number, r = R) => {
  const a = point(from, r);
  const b = point(to, r);
  return `M ${a.x.toFixed(2)} ${a.y.toFixed(2)} A ${r} ${r} 0 0 1 ${b.x.toFixed(2)} ${b.y.toFixed(2)}`;
};

interface Props { score: number; band: Band; thresholds: Thresholds | null }

/**
 * Half-circle dial. The dim track is split into the four decision zones at the *current* thresholds, so a drift
 * tightening is visible as the zones sliding left. The bright arc and the needle show where this case landed.
 */
export function ScoreGauge({ score, band, thresholds }: Props) {
  const cuts = thresholds ? [0, thresholds.step_up, thresholds.review, thresholds.decline, 1000] : null;
  const zones: Band[] = ["APPROVE", "STEP_UP", "REVIEW", "DECLINE"];
  const needleTip = point(score, R + 10);
  const needleBase = point(score, R - 22);
  const fill = BAND[band].fill;

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="mx-auto w-full max-w-[320px]" role="img"
        aria-label={`Risk score ${score} out of 1000, band ${BAND[band].label}`}>
        {cuts
          ? zones.map((z, i) => (
              <g key={z}>
                <path d={arc(cuts[i], cuts[i + 1])} fill="none" stroke={BAND[z].fill} strokeOpacity={0.22} strokeWidth={12} />
                {score > cuts[i] && (
                  <path d={arc(cuts[i], Math.min(cuts[i + 1], score))} fill="none" stroke={BAND[z].fill} strokeWidth={12} />
                )}
              </g>
            ))
          : <path d={arc(0, 1000)} fill="none" stroke="#213052" strokeWidth={12} />}
        {cuts && cuts.slice(1, 4).map((c) => {
          const a = point(c, R - 12);
          const b = point(c, R + 12);
          const l = point(c, R + 24);
          return (
            <g key={c}>
              <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#070c17" strokeWidth={2} />
              <text x={l.x} y={l.y} fontSize={9.5} fill="#93a2c4" textAnchor="middle" dominantBaseline="middle">{c}</text>
            </g>
          );
        })}
        <line x1={needleBase.x} y1={needleBase.y} x2={needleTip.x} y2={needleTip.y} stroke="#eef2fa" strokeWidth={2.5} strokeLinecap="round" />
        <text x={CX} y={CY - 22} textAnchor="middle" fontSize={44} fontWeight={600} fill="#eef2fa">{score}</text>
        <text x={CX} y={CY - 2} textAnchor="middle" fontSize={12} fontWeight={600} fill={fill}>{BAND[band].label}</text>
        <text x={CX - R} y={CY + 16} textAnchor="middle" fontSize={9.5} fill="#6b7ca3">0</text>
        <text x={CX + R} y={CY + 16} textAnchor="middle" fontSize={9.5} fill="#6b7ca3">1000</text>
      </svg>
      {thresholds && (
        <p className="mt-1 text-center text-2xs text-ink-400">
          Zones at current thresholds {thresholds.step_up} / {thresholds.review} / {thresholds.decline}
        </p>
      )}
    </div>
  );
}
