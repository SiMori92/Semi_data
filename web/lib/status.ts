import { crawlBadge, freshnessBadge, ivBadge, lastCrawlTime } from "./badges";
import type { Clock } from "./clock";
import type { Db } from "./db";
import type { Env } from "./env";

/** Everything the navbar shows, computed in one place (server-side only). */
export function statusPayload(db: Db, clock: Clock, env: Env) {
  return { lastCrawl: lastCrawlTime(db), freshness: freshnessBadge(db, clock), crawl: crawlBadge(db, clock, env), iv: ivBadge(db) };
}
