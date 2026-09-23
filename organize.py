#!/usr/bin/env python3
"""One-shot buku bookmark reorganization.

- strips import/folder artifact tags and scrape date codes
- merges synonyms, fixes typos
- assigns exactly one category tag per bookmark
- dry-run by default; --apply writes in one transaction
"""
import sqlite3
import sys
from collections import Counter

DB = "/Users/paulbaur/.local/share/buku/bookmarks.db"

# --- tags removed outright (browser folders, import stamps, site scrape noise)
JUNK = {
    "2026sep23", "other bookmarks", "bookmarks bar", "toolbar", "menu",
    "unfiled", "other", "mobile bookmarks", "b-list", "paul",
    "mozilla firefox", "msn websites", "microsoft websites", "windows live",
    "ubuntu setup", "ubuntu and free software links", "jan", "init", "used",
    "leaderboards", "_jav", "asm_2012-12-12", "videobox_2013-01-04a",
    "videobox_2013-01-04b", "downloading videobox 2012-11-12",
    "20101221a", "20101221b", "actionjav_2013-03-05a", "actionjav 2012-7-11a",
    "actionjav2012-12-03", "actionjav20130204", "horrormovies_2023",
    "eva angelina videobox pg1", "aubrey addams videobox pg2",
}

# tags redundant with the category assigned later; dropped after categorize
CATEGORY_EQUIV = {
    "dev", "life", "media", "adult", "ham-radio", "work", "devops",
    "woodwork", "news", "firearms", "audio", "ai", "apps", "vintage-comp",
    "ux", "photo", "home", "electronics",
    "ham radio", "woodworking", "vintage computing", "photography",
}

# --- synonym merges / typo fixes (applied after junk strip)
MERGE = {
    "download": "downloads",
    "java2018": "java",
    "node.js email utils": "node.js",
    "tkinter & figma": "tkinter,figma",  # split into two
    "to learn": "learning",
    "postcasts": "podcasts",
    "personalprotection": "self defense",
    "porn": None,  # replaced by category 'adult'
    "horrormovies_2023": "horrormovies",
    "expanse  the": "expanse",
}

# --- topic tag -> category
CAT = {}
def _cat(category, tags):
    for t in tags:
        CAT[t] = category

_cat("ham-radio", ["ham radio", "cw", "packet", "aprs", "satellite", "tentec"])
_cat("woodwork", ["woodworking", "lumber", "toolboxes",
    "tool vendors & manufacturers", "saws", "shaper", "hand planes",
    "workbench", "sharpening", "furniture", "cnc", "cardboard", "welding",
    "knots", "picture hanging", "log homes", "watchmaking"])
_cat("dev", ["python", "java", "node.js", "rails", "tkinter", "figma",
    "web dev", "programming", "javascript", "react", "golang", "scala",
    "rust", "elixir / erlang", "dotnet", "spring", "jpa", "infinispan",
    "activemq", "db2", "databases", "cassandra", "redis", "regex",
    "algorithms", "unit testing", "testing", "git", "mumps", "tk",
    "jupyter", "in28minutes", "microservices", "semantics", "sample data",
    "linux", "ubuntu", "shells", "apple", "android", "udemy", "coursera",
    "software", "engineering", "learning"])
_cat("ai", ["ai", "ai images", "machine learning"])
_cat("devops", ["docker", "docker dev environments", "ansible", "aws", "gcp",
    "nagios", "monitoring", "networking", "kubernetes", "serverless", "iac",
    "cloud", "backup", "log management", "caching", "package-manager",
    "security", "admin", "mainframe", "oracle", "pgp", "email"])
_cat("work", ["job search", "jobs", "wildfly", "wildfly project",
    "wildfly project2", "wildfly project3", "oam", "salesforce", "dev/uat",
    "voiceover", "headshots", "change management", "certification",
    "training", "production", "project management"])
_cat("firearms", ["firearms", "holsters", "knives", "walther", "sig sauer",
    "10mm", "5.56mm pistols", "hunting", "self defense", "gun control",
    "brass", "optics", "dealers"])
_cat("vintage-comp", ["vintage computing", "dec", "vintage", "pdp",
    "cosmac elf", "appleii", "zx spectrum", "analog computing", "sbc"])
_cat("photo", ["photography", "photographers", "photography courses"])
_cat("audio", ["audio", "recording", "microphone parts", "iems", "sax",
    "guitar", "music theory"])
_cat("ux", ["ux", "accessibility", "fonts", "graphics"])
_cat("electronics", ["electronics", "microcontroller", "iot"])
_cat("adult", ["victoriavalentino", "eva angelina", "aubrey addams"])
_cat("media", ["rumble", "movies", "tv & movies", "horrormovies", "expanse",
    "bittorrent", "downloads", "odysee", "comedy", "memes", "gaming"])
_cat("news", ["news", "politics", "substack", "covid", "economics",
    "links for united states"])
_cat("home", ["smarthome", "diy", "solar power", "tools", "hvac", "cleaning",
    "nas", "power", "iso"])
_cat("life", ["food", "coffee", "recipes", "meat", "chocolate", "restaurants",
    "month clubs", "travel", "england", "books", "health & fitness",
    "healthcare", "grooming", "athlete's foot", "braces", "eyeglasses",
    "big&tall", "clothing", "boots", "belts", "bags & packs", "balm",
    "gifts", "toys", "prepping", "motorcycles", "atv", "drones",
    "powersports", "rv", "airstream", "cars", "racing", "planespotting",
    "packers", "philosophy", "culture", "self improvement", "read list",
    "maps", "internet search", "socialmedia", "people", "thinkers",
    "podcasts", "homebrew", "drawing", "art", "hp", "google", "amazon",
    "pinterest", "online citrus", "bmo", "finance", "cryptocurrency",
    "makers", "rms", "printing", "pens  pencils  & markers", "recipes",
    "menus", "chinese", "ipad stylus"])
_cat("apps", [])  # web-app launchers and account pages

# category-only fallbacks for keyword hits
KEYWORD_CATS = [
    ("jav", "adult"), ("porn", "adult"), ("videobox", "adult"),
    ("ham", "ham-radio"), ("radio", "ham-radio"), ("antenna", "ham-radio"),
    ("sharkrf", "ham-radio"), ("aprs", "ham-radio"),
    ("wood", "woodwork"), ("saw", "woodwork"), ("sketchup", "woodwork"),
    ("stylus", "photo"), ("photo", "photo"), ("camera", "photo"),
    ("python", "dev"), ("program", "dev"), ("github", "dev"),
    ("codepen", "dev"), ("codesandbox", "dev"), ("oracle", "dev"),
    ("vscode", "dev"), ("visual studio", "dev"), ("dataset", "dev"),
    ("jenkins", "devops"), ("semaphore", "devops"), ("docker", "devops"),
    ("kubernetes", "devops"), ("ansible", "devops"), ("backstage", "devops"),
    ("wildfly", "work"), ("jboss", "work"), ("dodaf", "work"),
    ("dod ", "work"),
    ("gun", "firearms"), ("pistol", "firearms"), ("ammo", "firearms"),
    ("retro", "vintage-comp"), ("computing", "vintage-comp"),
    ("audio", "audio"), ("record", "audio"), ("microphone", "audio"),
    ("spotify", "media"), ("torrent", "media"), ("transmission", "media"),
    ("tv listing", "media"), ("tv schedule", "media"), ("zap2it", "media"),
    ("rumble", "media"), ("movie", "media"),
    ("news", "news"), ("politic", "news"),
    ("recipe", "life"), ("menu", "life"), ("casserole", "life"),
    ("router", "home"), ("wifi", "home"), ("printer", "home"),
    ("notebooklm", "ai"), ("colab", "ai"), ("machine learning", "ai"),
    ("gmail", "apps"), ("mail", "apps"), ("calendar", "apps"),
    ("feedly", "apps"), ("pocket", "apps"), ("adobe", "apps"),
    ("acrobat", "apps"), ("godaddy", "apps"), ("yahoo", "apps"),
    ("zight", "apps"), ("cacher", "apps"),
    ("micorp", "work"), ("minet", "work"), ("timesheet", "work"),
    ("sharepoint", "work"), ("mi-mke", "work"), ("missc", "work"),
    ("webtrends", "work"), ("concur", "work"), ("flexmls", "work"),
    ("crossware", "work"), ("applix", "work"), ("ibeam", "work"),
    ("sametime", "work"), ("skillsoft", "work"), ("testtrack", "work"),
    ("mvsd", "adult"), ("avbom", "adult"), ("subtitletrans", "adult"),
    ("123videos", "adult"),
    ("weather", "life"), ("wunderground", "life"), ("dmv", "life"),
    ("alltrails", "life"), ("trail", "life"), ("jalopyjournal", "life"),
    ("chevy", "life"), ("bmw", "life"), ("automobile", "life"),
    ("workout", "life"), ("fitness", "life"), ("sunjack", "life"),
    ("metalart", "life"),
    ("comic", "media"), ("marvel", "media"), ("dccomics", "media"),
    ("channel lineup", "media"), ("spectrum.com", "media"),
    ("tvlistings", "media"),
    ("kenrockwell", "photo"), ("drobo", "home"), ("robotime", "woodwork"),
    ("book nook", "woodwork"), ("openhistoricalmap", "life"),
    ("openstreetmap", "life"), ("nuclearpi", "vintage-comp"),
    ("google.com/search", "apps"), ("go.microsoft.com", "apps"),
    ("msn", "apps"), ("windows live", "apps"), ("aim express", "apps"),
    ("google talk", "apps"), ("aol.com", "apps"),
    ("w3schools", "dev"), ("builtwith", "dev"), ("bitcrowd", "dev"),
    ("launchschool", "dev"), ("tether", "dev"), ("eclipse che", "dev"),
    ("perf", "dev"), ("profil", "dev"), ("ibm", "dev"),
    ("tomcat", "devops"),
    ("bmo", "work"), ("mibank", "work"), ("checkarchive", "work"),
    ("webview", "work"), ("olbb", "work"), ("mieforms", "work"),
    ("mitil", "work"), ("miarchive", "work"), ("corresbank", "work"),
    ("bankreports", "work"), ("businessportal", "work"),
    ("awsapps", "work"),
    ("mozilla", "apps"), ("firefox", "apps"),
    ("centos", "dev"), ("ubuntu", "dev"), ("debian", "dev"),
    ("launchpad", "dev"), ("infoworld", "dev"), ("sourcesafe", "dev"),
    ("diagrams.net", "dev"), ("code.google.com", "dev"),
    ("www.google.com", "apps"), ("evernote", "apps"),
    ("linux", "devops"), ("backup", "devops"), ("ssh", "devops"),
    ("zsh", "devops"), ("jdk", "devops"), ("jre", "devops"),
    ("weblogic", "devops"), ("technet", "devops"), ("free/busy", "devops"),
    ("exchange", "devops"), ("microsoft.com/kb", "devops"),
    ("password", "devops"), ("grc.com", "devops"), ("certificate", "devops"),
    ("sslshopper", "devops"), ("syncthing", "devops"),
    ("tailscale", "devops"), ("uptime kuma", "devops"), ("root-me", "devops"),
    ("amp", "audio"), ("guitar", "audio"), ("vst", "audio"),
    ("synth", "audio"), ("reverb", "audio"), ("pluginguru", "audio"),
    ("mojotone", "audio"), ("tubestore", "audio"), ("syntherjack", "audio"),
    ("youtube", "media"), ("techwatch", "news"), ("digital shield", "news"),
    ("how to ai", "ai"),
    ("hodgsonconsult", "dev"), ("lc3", "dev"), ("git-scm", "dev"),
    ("apple.com/shop", "life"),
]

# --- keyword rules on tags we did not map (title/url fallback next)

def parse_tags(raw):
    return [t.strip() for t in raw.strip(",").split(",") if t.strip()]

def normalize(tags):
    out = []
    for t in tags:
        if t in JUNK:
            continue
        t = MERGE.get(t, t)
        if t is None:
            continue
        for part in t.split(","):
            part = part.strip()
            if part and part not in out:
                out.append(part)
    return out

def categorize(tags, title, url):
    for t in tags:
        if t in CAT:
            return CAT[t]
    hay = (title + " " + url).lower()
    for kw, c in KEYWORD_CATS:
        if kw in hay:
            return c
    return "unsorted"

def main():
    apply = "--apply" in sys.argv
    con = sqlite3.connect(DB)
    rows = con.execute(
        "SELECT id, URL, metadata, tags FROM bookmarks").fetchall()

    cat_counts = Counter()
    updates = []
    for rid, url, title, raw in rows:
        tags = normalize(parse_tags(raw))
        cat = categorize(tags, title, url)
        cat_counts[cat] += 1
        newtags = [cat] + [
            t for t in tags if t != cat and t not in CATEGORY_EQUIV]
        updates.append((rid, "," + ",".join(newtags) + ",", raw))

    print("category counts:")
    for c, n in cat_counts.most_common():
        print(f"  {c:14} {n}")

    stripped = Counter()
    for rid, _, _, raw in rows:
        for t in parse_tags(raw):
            if t in JUNK:
                stripped[t] += 1
    print("\njunk tags stripped:")
    for t, n in stripped.most_common():
        print(f"  {t:35} {n}")

    print("\nrows with changed tags:", sum(
        1 for _, new, old in updates if new != old))

    print("\nunsorted rows:")
    for (rid, url, title, raw), (rid2, new, _) in zip(rows, updates):
        if new.split(",")[1] == "unsorted":
            print(f"  {rid:5} {title[:60]:60} {url[:70]}")

    if apply:
        with con:
            con.executemany(
                "UPDATE bookmarks SET tags = ? WHERE id = ? AND tags = ?",
                [(new, rid, old) for rid, new, old in updates])
        print("\nAPPLIED")
    else:
        print("\nDRY RUN - rerun with --apply to write")
    con.close()

if __name__ == "__main__":
    main()
