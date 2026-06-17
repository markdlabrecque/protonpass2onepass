#!/usr/bin/env python3
"""Proton Pass -> 1Password (.1pux) converter.

    python3 convert.py --in export.zip --out account.1pux [--alias-as login|note]
                       [--skip itemId,itemId] [--email you@example.com]

Standard library only. Reads/writes local paths. Never prints field values.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import zipfile

from proton2onepass import reader, writer
from proton2onepass.mappers import map_item

VAULT_TYPE = {"P": "P"}  # Proton 'P' (Private) -> 1Password personal; others -> 'U'


def _slug(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s or "item").strip("_")
    return s or "item"


def extract_attachments(export: reader.ProtonExport, items_with_files, dest: str) -> list[dict]:
    """Copy referenced attachment files out of the archive for manual re-attach.

    Returns report rows. Never reads file *content* into logs.
    """
    rows = []
    if not items_with_files:
        return rows
    os.makedirs(dest, exist_ok=True)
    with zipfile.ZipFile(export.archive_path) as zf:
        names = set(zf.namelist())
        for item in items_with_files:
            meta = item.get("data", {}).get("metadata", {}) or {}
            title = meta.get("name", "") or item.get("itemId", "item")
            item_dir = os.path.join(dest, _slug(title))
            os.makedirs(item_dir, exist_ok=True)
            for rel in item.get("files") or []:
                arc = export.files_prefix + rel
                if arc not in names:
                    rows.append({"title": title, "file": rel, "status": "MISSING in archive"})
                    continue
                with zf.open(arc) as src:
                    out = os.path.join(item_dir, _slug(rel))
                    with open(out, "wb") as fh:
                        fh.write(src.read())
                rows.append({"title": title, "file": rel, "status": "extracted",
                             "path": os.path.relpath(out)})
    return rows


def write_report(path: str, ctx: dict) -> None:
    L = []
    L.append("# Proton Pass -> 1Password conversion report\n")
    L.append(f"- Source: `{os.path.basename(ctx['in'])}` (Proton export version "
             f"{ctx['version']})")
    L.append(f"- Output: `{os.path.basename(ctx['out'])}`")
    L.append(f"- Total items in source: **{ctx['total']}**")
    L.append(f"- Converted: **{ctx['converted']}**")
    trashed_word = "converted (--include-trashed)" if ctx["include_trashed"] else "skipped"
    L.append(f"- In Proton trash (state=2): **{ctx['trashed']}** — {trashed_word}")
    L.append(f"- Skipped (via --skip flag): **{ctx['skipped_flag']}**\n")

    L.append("## Item counts by type (converted)\n")
    for t, n in sorted(ctx["by_type"].items()):
        L.append(f"- `{t}`: {n}")
    L.append("")

    L.append("## Item counts per vault (reconciliation)\n")
    inc = ctx["include_trashed"]
    for name, v in ctx["per_vault"].items():
        # when --include-trashed, trashed items are counted within 'conv' too
        accounted = v["conv"] + v["skip"] + (0 if inc else v["trash"])
        flag = "" if accounted == v["src"] else "  ⚠️ UNACCOUNTED LOSS"
        trash_note = f" (trash {v['trash']} included)" if inc else f" + trash {v['trash']}"
        L.append(f"- **{name}**: source {v['src']} = converted {v['conv']} "
                 f"+ skipped {v['skip']}{trash_note}{flag}")
    L.append("")

    L.append("## Passkeys — NOT migrated (re-register manually)\n")
    if ctx["passkeys"]:
        L.append("Passkeys are device-bound and cannot be imported from a file. "
                 "Re-register each on the site after import:\n")
        for row in ctx["passkeys"]:
            L.append(f"- **{row['title']}** — {row['count']} passkey(s)"
                     + (f" — {', '.join(row['domains'])}" if row['domains'] else ""))
    else:
        L.append("None found.")
    L.append("")

    L.append("## Attachments — extracted for manual re-attach\n")
    if ctx["attachments"]:
        L.append(f"Extracted to `{ctx['attachments_dir']}`. 1Password file import "
                 "of these is not done automatically; attach them by hand to the "
                 "matching item after import:\n")
        for row in ctx["attachments"]:
            note = row.get("path", row["status"])
            L.append(f"- **{row['title']}** — `{row['file']}` → {note}")
    else:
        L.append("None found.")
    L.append("")

    if ctx["unknown_types"]:
        L.append("## Unknown item types (mapped to Secure Note)\n")
        for t, n in sorted(ctx["unknown_types"].items()):
            L.append(f"- `{t}`: {n}")
        L.append("")

    L.append("## Notes / caveats\n")
    L.append("- Credit-card `type` (Proton's numeric enum) is not carried over; "
             "set the card brand manually if needed.")
    L.append("- Identity items land with their fields in a single section "
             "(values preserved); they are not mapped to 1Password's native "
             "identity template slots.")
    L.append("- Field ordering within an item is best-effort.")

    with open(path, "w") as fh:
        fh.write("\n".join(L) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="Proton Pass -> 1Password .1pux converter")
    ap.add_argument("--in", dest="inp", required=True, help="Proton export .zip")
    ap.add_argument("--out", required=True, help="output .1pux path")
    ap.add_argument("--alias-as", choices=["login", "note"], default="login",
                    help="how to land SimpleLogin aliases (default: login)")
    ap.add_argument("--skip", default="", help="comma-separated Proton itemIds to skip")
    ap.add_argument("--include-trashed", action="store_true",
                    help="also convert items in Proton's trash (state=2); default skips them")
    ap.add_argument("--email", default="import@example.com",
                    help="cosmetic account email written into the export")
    opts = ap.parse_args()

    if not os.path.isfile(opts.inp):
        ap.error(f"input not found: {opts.inp}")
    skip_ids = {s.strip() for s in opts.skip.split(",") if s.strip()}

    export = reader.load(opts.inp)

    total = converted = trashed = skipped_flag = 0
    by_type: dict[str, int] = {}
    unknown_types: dict[str, int] = {}
    per_vault: dict[str, dict] = {}
    passkeys = []
    items_with_files = []
    known = {"login", "alias", "note", "custom", "creditCard", "identity"}

    vault_blocks = []
    for vid, vault in export.vaults.items():
        vname = vault.get("name", "") or "Proton Pass"
        items = vault.get("items", []) or []
        pv = per_vault.setdefault(vname, {"src": 0, "conv": 0, "trash": 0, "skip": 0})
        out_items = []
        for item in items:
            total += 1
            pv["src"] += 1
            if item.get("itemId") in skip_ids:
                skipped_flag += 1
                pv["skip"] += 1
                continue
            if item.get("state", 1) != 1:
                trashed += 1
                pv["trash"] += 1
                if not opts.include_trashed:
                    continue
            data = item.get("data", {})
            content = data.get("content", {}) or {}
            meta = data.get("metadata", {}) or {}
            # report scans (no secret values)
            if content.get("passkeys"):
                pk = content["passkeys"]
                passkeys.append({
                    "title": meta.get("name", "") or "(untitled)",
                    "count": len(pk),
                    "domains": sorted({p.get("domain", "") for p in pk if p.get("domain")}),
                })
            if item.get("files"):
                items_with_files.append(item)

            one_item, itype = map_item(item, opts)
            out_items.append(one_item)
            converted += 1
            pv["conv"] += 1
            by_type[itype] = by_type.get(itype, 0) + 1
            if itype not in known:
                unknown_types[itype] = unknown_types.get(itype, 0) + 1

        vtype = VAULT_TYPE.get(vault.get("type", ""), "U") if not vault_blocks else "U"
        vault_blocks.append(writer.vault_block(vname, vault.get("description", ""),
                                               out_items, vtype))

    account = writer.account_block(vault_blocks, email=opts.email)
    writer.write(opts.out, [account])

    out_dir = os.path.dirname(os.path.abspath(opts.out))
    stem = os.path.splitext(os.path.basename(opts.out))[0]
    attachments_dir = os.path.join(out_dir, f"{stem}_attachments")
    attach_rows = extract_attachments(export, items_with_files, attachments_dir)

    report_path = os.path.join(out_dir, f"{stem}-report.md")
    write_report(report_path, {
        "in": opts.inp, "out": opts.out, "version": export.version,
        "total": total, "converted": converted, "trashed": trashed,
        "include_trashed": opts.include_trashed,
        "skipped_flag": skipped_flag, "by_type": by_type,
        "unknown_types": unknown_types,
        "per_vault": per_vault,
        "passkeys": passkeys, "attachments": attach_rows,
        "attachments_dir": os.path.relpath(attachments_dir) if attach_rows else "",
    })

    # summary — counts only, no field values
    print(f"Converted {converted}/{total} items "
          f"({trashed} trashed, {skipped_flag} skipped via flag).")
    print(f"  by type: {by_type}")
    print(f"  passkeys not migrated: {sum(p['count'] for p in passkeys)} "
          f"across {len(passkeys)} logins")
    print(f"  attachments extracted: {len([r for r in attach_rows if r['status']=='extracted'])}")
    print(f"Wrote: {opts.out}")
    print(f"Report: {report_path}")
    if attach_rows:
        print(f"Attachments: {attachments_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
