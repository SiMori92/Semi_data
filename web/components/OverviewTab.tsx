/** Overview tab (Server Component): data from lib/overview.ts, charts on the client. */
import { MetricCard } from "./MetricCard";
import { Card, SourceFooter } from "./Card";
import { PlotlyChart } from "./PlotlyChart";
import { GREEN, RED, SUBTEXT } from "@/lib/config";
import type { OverviewResult } from "@/lib/overview";

export function OverviewTab({ r }: { r: OverviewResult }) {
  if (r.kind === "empty") return <Card><p style={{ color: RED }}>{r.message}</p></Card>;
  return (
    <div>
      <div className="metric-grid">
        {r.kpis.map((k) => <MetricCard key={k.label} label={k.label} value={k.value}
          colour={k.value_colour} note={k.delta} noteColour={k.delta_colour === GREEN ? GREEN : k.delta_colour === RED ? RED : SUBTEXT} />)}
      </div>
      <Card><PlotlyChart figure={r.priceFig} displayModeBar /></Card>
      <Card>
        {r.heatmap ? <PlotlyChart figure={r.heatmap} displayModeBar={false} />
          : <p style={{ color: SUBTEXT }}>{r.heatmapMessage}</p>}
      </Card>
      <Card><SourceFooter {...r.footer} /></Card>
    </div>
  );
}

