/** Overview tab (Server Component): data from lib/overview.ts, charts on the client. */
import { Card, SourceFooter } from "./Card";
import { PlotlyChart } from "./PlotlyChart";
import { GREEN, RED, SUBTEXT } from "@/lib/config";
import type { OverviewResult } from "@/lib/overview";

export function OverviewTab({ r }: { r: OverviewResult }) {
  if (r.kind === "empty") return <Card><p style={{ color: RED }}>{r.message}</p></Card>;
  return (
    <div>
      <div className="row g-2" style={{ marginBottom: 12 }}>
        {r.kpis.map((k) => (
          <div key={k.label} className="col-2 dashboard-kpi-col">
            <Card style={{ textAlign: "center" }}>
              <div style={{ padding: "8px 0" }}>
                <div style={{ fontSize: 11, color: SUBTEXT, textTransform: "uppercase", letterSpacing: 0.5 }}>{k.label}</div>
                <div style={{ fontSize: 22, fontWeight: 700, color: k.value_colour }}>{k.value}</div>
                <div style={{ fontSize: 12, color: k.delta_colour === GREEN ? GREEN : k.delta_colour === RED ? RED : SUBTEXT }}>{k.delta}</div>
              </div>
            </Card>
          </div>
        ))}
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

