#!/usr/bin/env python3
"""Check all bookmark URLs, tag unreachable ones with __dead."""
import sqlite3
import ssl
import sys
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor

DB = "/Users/paulbaur/.local/share/buku/bookmarks.db"
DEAD_TAG = "__dead"
TIMEOUT = 12
WORKERS = 24

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def check(url):
    for attempt in (1, 2):  # retry once: cuts transient false positives
        for method in ("HEAD", "GET"):
            try:
                req = urllib.request.Request(
                    url, method=method,
                    headers={"User-Agent": "Mozilla/5.0 (bookmark checker)"})
                with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
                    if r.status < 400:
                        return False
            except urllib.error.HTTPError as e:
                if e.code == 405 and method == "HEAD":
                    continue  # server rejects HEAD; try GET
                if 400 <= e.code < 500 and e.code not in (408, 429):
                    return True  # definitive client error
            except Exception:
                pass
        if attempt == 1:
            import time
            time.sleep(2)
    return True

def main():
    apply = "--apply" in sys.argv
    con = sqlite3.connect(DB)
    rows = con.execute("SELECT id, URL, tags FROM bookmarks").fetchall()

    with ThreadPoolExecutor(WORKERS) as ex:
        results = list(ex.map(lambda r: (r[0], r[2], check(r[1])), rows))

    dead = [(rid, tags) for rid, tags, is_dead in results if is_dead]
    print(f"checked: {len(results)}  dead: {len(dead)}")

    if apply:
        updates = []
        for rid, tags in dead:
            tag_list = [t for t in tags.strip(",").split(",") if t]
            if DEAD_TAG not in tag_list:
                tag_list.append(DEAD_TAG)
            updates.append(("," + ",".join(tag_list) + ",", rid))
        with con:
            con.executemany(
                "UPDATE bookmarks SET tags = ? WHERE id = ?", updates)
        print("APPLIED __dead tags")
    else:
        for rid, tags in dead[:40]:
            print(f"  {rid}")
    con.close()

if __name__ == "__main__":
    main()
