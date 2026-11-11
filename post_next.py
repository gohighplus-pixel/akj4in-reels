#!/usr/bin/env python3
"""Post the next due reel from queue_cloud.json to the Instagram account (Graph API, video_url).
Runs inside a Claude cloud routine. NO token anywhere: the environment attaches the Authorization header to
requests going to graph.facebook.com, so curl is called without credentials.
usage: post_next.py [--dry-run] [--no-sleep]
Guards: skip if the reel's title is already on the account; skip the slot if anything was posted in the last
120 minutes; never retry a publish whose outcome is uncertain (prints UNCERTAIN and stops)."""
import json, sys, subprocess, time, random, datetime as dt, urllib.parse, os

IG = "17841441939311632"; API = "https://graph.facebook.com/v27.0"
DRY = "--dry-run" in sys.argv
Q = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "queue_cloud.json")))


def call(method, path, params=None, timeout=120):
    args = ["curl", "-sS", "--max-time", str(timeout)]
    url = f"{API}/{path}"
    if method == "GET":
        url += "?" + urllib.parse.urlencode(params or {})
    else:
        args += ["-X", "POST"]
        for k, v in (params or {}).items(): args += ["--data-urlencode", f"{k}={v}"]
    r = subprocess.run(args + [url], capture_output=True, text=True)
    if r.returncode: raise RuntimeError(f"curl {r.returncode}: {r.stderr[:300]}")
    d = json.loads(r.stdout or "{}")
    if isinstance(d, dict) and "error" in d: raise RuntimeError("API error: " + json.dumps(d["error"])[:400])
    return d


def recent(n=40): return call("GET", f"{IG}/media", {"fields": "id,caption,permalink,timestamp", "limit": n}).get("data", [])


def first(c): return (c or "").split("\n")[0].strip().lower()


def main():
    now = dt.datetime.now(dt.timezone.utc)
    media = recent()
    done = {first(m.get("caption")) for m in media}
    nxt = next((e for e in Q if first(e["title"]) not in done), None)
    if not nxt: print("queue empty or all titles already on the account"); return
    slot = dt.datetime.fromisoformat(nxt["slot"])
    left = sum(1 for e in Q if first(e["title"]) not in done)
    print(f"next: #{nxt['n']} {nxt['title']} (slot {nxt['slot']}); {left} reels left in uploaded queue")
    if left <= 14: print("LOW RUNWAY: fewer than 14 uploaded reels left - tell the user to top up the queue")
    if now < slot - dt.timedelta(minutes=10): print("not due yet"); return
    if media:
        last = dt.datetime.strptime(media[0]["timestamp"], "%Y-%m-%dT%H:%M:%S%z")
        if now - last < dt.timedelta(minutes=120):
            print(f"SKIP: account posted {media[0]['permalink']} {int((now - last).total_seconds() // 60)} min ago"); return
    if DRY: print("DRY RUN: would publish", nxt["url"]); return
    if "--no-sleep" not in sys.argv: time.sleep(random.randint(0, 360))
    c = call("POST", f"{IG}/media", {"media_type": "REELS", "video_url": nxt["url"], "caption": nxt["caption"], "share_to_feed": "true"})
    cid = c["id"]; print("container", cid)
    for _ in range(60):
        s = call("GET", cid, {"fields": "status_code,status"})
        if s.get("status_code") == "FINISHED": break
        if s.get("status_code") in ("ERROR", "EXPIRED"): raise RuntimeError(f"processing failed: {s}")
        time.sleep(10)
    else: raise RuntimeError("processing timed out (nothing published)")
    try:
        mid = call("POST", f"{IG}/media_publish", {"creation_id": cid}, timeout=180)["id"]
    except Exception as e:
        time.sleep(60)
        if first(nxt["title"]) in {first(m.get("caption")) for m in recent(10)}: print("PUBLISHED (confirmed on re-check)"); return
        print("UNCERTAIN: publish call failed and the post is not visible:", e); sys.exit(2)
    pl = call("GET", mid, {"fields": "permalink,timestamp"})
    print("PUBLISHED", nxt["n"], nxt["title"], pl.get("permalink"), pl.get("timestamp"))


if __name__ == "__main__":
    try: main()
    except SystemExit: raise
    except Exception as e: print("ERROR:", e); sys.exit(1)
