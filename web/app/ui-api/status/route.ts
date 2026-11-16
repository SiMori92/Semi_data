/**
 * Navbar status for the 30-s poll. Lives under /ui-api/, NOT /api/: during the
 * strangler phase every /api/* path belongs to Flask and is proxied unchanged.
 */
import { systemClock } from "@/lib/clock";
import { getEnv } from "@/lib/env";
import { getDb } from "@/lib/server";
import { statusPayload } from "@/lib/status";

export const dynamic = "force-dynamic";

export function GET() {
  return Response.json(statusPayload(getDb(), systemClock(), getEnv()), { headers: { "Cache-Control": "no-store" } });
}
