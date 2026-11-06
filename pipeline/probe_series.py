"""Probe (wip only): which Kalshi sports series aren't on the site yet, and what do their markets look like?"""
import json
import os
import re
import time

from .net import get_json
from .sports import BASE, CORE, SERIES_RE, SKIP_STEM

OUT = os.environ.get("PROP_OUT", "debug")
PLAYERISH = re.compile(r"yards|points|rebounds|assists|goal|touchdown|\bTDs?\b|reception|strikeout|\bhits?\b|home run|"
                       r"shots|saves|aces|kills|threes|3-point|passing|rushing|receiving|scorer|player|RBI|bases|"
                       r"steals|blocks|tackles|sacks|interception|completions|pitcher|batter", re.I)


def main():
    t0 = time.time()
    d = get_json(BASE + "/series", params={"category": "Sports"})
    series = d.get("series") or []
    out = {"total": len(series), "unmatched": [], "player": []}
    for s in series:
        t = s.get("ticker") or ""
        if t.startswith(CORE) or SERIES_RE.match(t):
            continue
        row = {"t": t, "title": s.get("title"), "tags": s.get("tags"), "skip": bool(SKIP_STEM.search(t))}
        out["unmatched"].append(row)
    cands = [r for r in out["unmatched"] if PLAYERISH.search(r["title"] or "") and not r["skip"]]
    print(f"{len(series)} sports series, {len(out['unmatched'])} not on the site, {len(cands)} look like player props")
    for r in cands:
        info = dict(r)
        try:
            o = get_json(BASE + "/markets", params={"series_ticker": r["t"], "status": "open", "limit": 1000})
            mk = o.get("markets") or []
            info["open"] = len(mk)
            info["events"] = len({m.get("event_ticker") for m in mk})
            info["sample"] = [{k: m.get(k) for k in ("ticker", "event_ticker", "title", "subtitle", "yes_sub_title",
                                                       "floor_strike", "strike_type", "custom_strike", "yes_bid_dollars",
                                                       "yes_ask_dollars", "volume_fp", "volume", "occurrence_datetime",
                                                       "expected_expiration_time")} for m in mk[:3]]
            if mk:
                info["rules"] = (mk[0].get("rules_primary") or "")[:300]
            time.sleep(0.08)
            st = get_json(BASE + "/markets", params={"series_ticker": r["t"], "status": "settled", "limit": 200})
            sm = st.get("markets") or []
            info["settled_page"] = len(sm)
            info["settled_sample"] = [{k: m.get(k) for k in ("ticker", "event_ticker", "yes_sub_title", "floor_strike",
                                                               "result", "expiration_value", "close_time")} for m in sm[:4]]
            time.sleep(0.08)
        except Exception as e:  # noqa: BLE001
            info["error"] = repr(e)[:200]
        out["player"].append(info)
    out["player"].sort(key=lambda x: -(x.get("open") or 0))
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "series.json"), "w") as f:
        json.dump(out, f, indent=1)
    for x in out["player"]:
        print(f"{x['t']:28} open {x.get('open', '?'):>5} events {x.get('events', '?'):>4} settled {x.get('settled_page', '?'):>4}  "
              f"{(x['title'] or '')[:60]}  tags={x['tags']}")
    print(f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
