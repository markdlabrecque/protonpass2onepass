#!/usr/bin/env python3
"""Round-trip diff: which Proton items did NOT make it into 1Password?

Compare the SOURCE Proton export against a .1pux you exported back out of the
vault you imported into. Matches on item title (metadata.name -> overview.title)
as a multiset, so duplicate titles are handled. Prints only titles/types — no
secret values.

    python3 diff_import.py --source export.zip --exported roundtrip.1pux
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from collections import Counter


def _read_zip_member(path, endswith=None, exact=None):
    with zipfile.ZipFile(path) as zf:
        if exact:
            return zf.read(exact)
        for n in zf.namelist():
            if n.endswith(endswith) and not n.endswith("/"):
                return zf.read(n)
    raise FileNotFoundError(endswith or exact)


def source_titles(path, include_trashed=False, skip_ids=frozenset()):
    data = json.loads(_read_zip_member(path, endswith="data.json"))
    rows = []
    for vault in data.get("vaults", {}).values():
        for it in vault.get("items", []) or []:
            if it.get("itemId") in skip_ids:
                continue
            if it.get("state", 1) != 1 and not include_trashed:
                continue
            meta = it.get("data", {}).get("metadata", {}) or {}
            rows.append((meta.get("name", "") or "(untitled)",
                         it.get("data", {}).get("type", "?")))
    return rows


def exported_titles(path):
    data = json.loads(_read_zip_member(path, exact="export.data"))
    out = []
    for acct in data.get("accounts", []):
        for vault in acct.get("vaults", []):
            for it in vault.get("items", []):
                out.append(it.get("overview", {}).get("title", "") or "(untitled)")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="original Proton export .zip")
    ap.add_argument("--exported", required=True, help="round-trip .1pux exported from 1Password")
    ap.add_argument("--include-trashed", action="store_true")
    ap.add_argument("--skip", default="")
    args = ap.parse_args()
    skip_ids = {s.strip() for s in args.skip.split(",") if s.strip()}

    src = source_titles(args.source, args.include_trashed, skip_ids)
    src_types = {t: ty for t, ty in src}
    src_count = Counter(t for t, _ in src)
    exp_count = Counter(exported_titles(args.exported))

    # multiset difference: present in source, fewer (or none) in export
    missing = src_count - exp_count
    total_missing = sum(missing.values())

    print(f"Source items considered: {sum(src_count.values())}")
    print(f"Exported items found:    {sum(exp_count.values())}")
    print(f"Likely NOT imported:     {total_missing}\n")

    by_type = Counter()
    for title, n in missing.most_common():
        ty = src_types.get(title, "?")
        by_type[ty] += n
        suffix = f"  (x{n})" if n > 1 else ""
        print(f"  [{ty:10}] {title}{suffix}")

    print(f"\nMissing by type: {dict(by_type)}")
    print("\nNote: matches on title only. If one of your pre-existing 1Password "
          "items shares a title with a source item, that source item may look "
          "'imported' here even if it wasn't.")


if __name__ == "__main__":
    sys.exit(main())
