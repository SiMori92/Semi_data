# Header artwork

The shared header selects a painting on each dashboard tab visit, refresh, or return via the browser's back/forward cache. A shuffled bag in sessionStorage shows every catalogued work once before starting another cycle and avoids an immediate repeat between cycles. Normal polling and filter changes do not reshuffle. When browser storage is blocked, an in-memory bag supports navigation; reload history cannot be retained in that case.

## Catalogue (UI-02)

The collection is a URL catalogue of 100+ public-domain Impressionist and Post-Impressionist works in `web/lib/artwork-catalog.json`, generated from the **Google Art Project** scans on Wikimedia Commons (`Category:Google Art Project works by <artist>`) by `Product/next_rebuild/scripts/build-art-catalog.mjs`. Never hand-edit the JSON; re-run the script and review the diff.

Each entry records artist, title, year, a 1280 px Commons thumbnail URL (`image`), the matching Google Arts & Culture asset (`source`, taken from the file's Credit line), the Commons file page (`commons`) and its licence. The script keeps a work only when Commons marks it not copyrighted (PD / CC0), it carries a Google Arts & Culture asset id, a title and year parse, its original is at least 1280 px wide, and it is landscape (width/height ≥ 1.15) so the wide header crop works.

Images are loaded by the browser from Wikimedia's CDN (`upload.wikimedia.org` / `thumb.wikimedia.org`); the app server never fetches them. Google Arts & Culture is the discovery/reference destination that captions link to, not a live image feed.

## Local fallback

Only one image is stored here, used when the selected remote image fails to load (offline, blocked host):

| Local file                        | Work                                                 | Google Arts & Culture                                  | Image source / rights                                                                                                                                                  |
| --------------------------------- | ---------------------------------------------------- | ------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `caillebotte-paris-rainy-day.jpg` | Gustave Caillebotte, _Paris Street; Rainy Day_, 1877 | https://artsandculture.google.com/asset/5wEUCOlEf-EaVQ | https://commons.wikimedia.org/wiki/File:Gustave_Caillebotte_-_Paris_Street;_Rainy_Day_-_Google_Art_Project.jpg · Public domain; Art Institute of Chicago artwork 20684 |

If the fallback also fails, the header shows "Artwork unavailable" with no caption.

The app-specific storage key is `semi-artwork-shuffle-v2`. Bump `artworkStorageKey` in `web/lib/artwork.ts` whenever the catalogue changes so existing sessions start a fresh bag.
