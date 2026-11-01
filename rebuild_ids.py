#!/usr/bin/env python3
"""Rebuild ids.json from the ID data files in ids/ (laptop, v7.1).

IDs are NOT fixed: names change and new IDs keep coming. So ids.json is a
GENERATED file, not a one-time snapshot. Run this script whenever IDs were
created, renamed, or had their cookies refreshed, and the browser's IDs
section picks the new list up at once (the server reads ids.json fresh on
every /api/ids request — no restart needed).

Sources (all inside the ids/ folder next to this script):
  - ids/new_cookies.txt  : uid|password|cookies (clean Facebook cookies)
  - ids/new_ids_50.txt   : uid|password|<Facebook cookie string>|...
                            field2 holds the Facebook cookies (c_user/xs/...)
  - ids/indian_names.md  : rename mapping table
                            | # | UID | Current name | Gender | New Indian name |

Merge rules (safe to re-run any time):
  - Existing ids.json entries are kept as the base, so IDs added by hand
    through the browser's "Add ID" form are never lost.
  - Data files update cookies/names for a UID, and add UIDs that are new.
  - For cookies, prefer the string that contains c_user= (logged-in);
    if both have it, prefer new_ids_50.txt (fresher).
  - A UID is never deleted by a rebuild (dead IDs are removed by hand
    from ids.json, or by the browser's list — see README-IDS.md).

Run:  python rebuild_ids.py        (from this folder)
"""
import json
import os
import re

BASE = os.path.dirname(os.path.abspath(__file__))
IDS_DIR = os.path.join(BASE, "ids")
NEW_COOKIES = os.path.join(IDS_DIR, "new_cookies.txt")
NEW_IDS_50 = os.path.join(IDS_DIR, "new_ids_50.txt")
NAMES_MD = os.path.join(IDS_DIR, "indian_names.md")
OUT = os.path.join(BASE, "ids.json")


def read_new_cookies(path):
    out = {}
    if not os.path.isfile(path):
        return out
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("|")
            if len(parts) < 3:
                continue
            uid, password, cookies = parts[0].strip(), parts[1].strip(), parts[2].strip()
            if not uid or not cookies:
                continue
            out[uid] = {"password": password, "cookies": cookies, "source": "new_cookies.txt"}
    return out


def read_new_ids_50(path):
    out = {}
    if not os.path.isfile(path):
        return out
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("|")
            if len(parts) < 3:
                continue
            uid, password, cookies = parts[0].strip(), parts[1].strip(), parts[2].strip()
            if not uid or not cookies or "=" not in cookies:
                continue
            out[uid] = {"password": password, "cookies": cookies, "source": "new_ids_50.txt"}
    return out


def read_names(path):
    out = {}
    if not os.path.isfile(path):
        return out
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = re.match(r"\|\s*(\d+)\s*\|\s*(\d{10,})\s*\|\s*([^|]*)\|\s*([MF])\s*\|\s*([^|]*)\|", line)
            if not m:
                continue
            num, uid, cur, gender, new = m.groups()
            out[uid] = {"num": int(num), "name": cur.strip(),
                        "gender": gender, "new_name": new.strip()}
    return out


def pick_cookies(ea, eb):
    """Prefer the cookie string with c_user=; if both have it, prefer eb
    (new_ids_50.txt, fresher). Returns (entry, ) or None."""
    for cand in (eb, ea):
        if cand and "c_user=" in cand["cookies"]:
            return cand
    return eb or ea


def main():
    existing = {}
    if os.path.isfile(OUT):
        try:
            with open(OUT, encoding="utf-8") as f:
                data = json.load(f)
            for e in data.get("ids", []):
                existing[e["uid"]] = e
        except Exception:
            pass
    a = read_new_cookies(NEW_COOKIES)
    b = read_new_ids_50(NEW_IDS_50)
    names = read_names(NAMES_MD)
    uids = sorted(set(existing) | set(a) | set(b))
    ids = []
    for uid in uids:
        base = dict(existing.get(uid, {}))
        ea, eb = a.get(uid), b.get(uid)
        pick = pick_cookies(ea, eb)
        if pick is not None:
            base["password"] = pick["password"]
            base["cookies"] = pick["cookies"]
            base["source"] = pick["source"]
        nm = names.get(uid)
        if nm:
            base["num"] = nm["num"]
            base["name"] = nm["name"]
            base["gender"] = nm["gender"]
            base["new_name"] = nm["new_name"]
        base["uid"] = uid
        base.setdefault("name", "")
        base.setdefault("gender", "")
        base.setdefault("new_name", "")
        base.setdefault("num", None)
        base.setdefault("password", "")
        base.setdefault("cookies", "")
        base.setdefault("source", "manual")
        base["has_c_user"] = "c_user=" in (base.get("cookies") or "")
        ids.append(base)
    ids.sort(key=lambda e: (e.get("num") is None, e.get("num") or 0, e["uid"]))
    data = {"generated": "rebuild_ids.py (IDs grow and change — re-run after new IDs / renames)",
            "count": len(ids),
            "with_c_user": sum(1 for e in ids if e["has_c_user"]),
            "ids": ids}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print("ids:", len(ids), "with c_user:", data["with_c_user"], "->", OUT)


if __name__ == "__main__":
    main()
