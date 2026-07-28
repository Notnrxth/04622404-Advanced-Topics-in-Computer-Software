"""Run the Cleaning + Normalization stage over the Collection stage output.

    python Pipeline/02_data_cleaning.py

Reads Pipeline/outputs/extracted_text_*.json, writes cleaned_*.json next to
them, and prints a before/after sample plus a check that no record lost its
"id" or any structured field.
"""

import json
from pathlib import Path

from cleaning import TEXT_FIELDS, collect_boilerplate, process_records

OUTPUTS = Path(__file__).resolve().parent / "outputs"
PREVIEW = 320


def preview(text):
    """One-line, truncated view of a text field so before/after fit on screen."""
    flat = text.replace("\n", " | ")
    return flat[:PREVIEW] + ("..." if len(flat) > PREVIEW else "")


def check_structure(before, after):
    """Raise if any record lost its id, gained/lost a key, or changed a non-text value."""
    assert len(before) == len(after), "record count changed"
    for old, new in zip(before, after):
        assert old["id"] == new["id"], f"id changed: {old['id']} -> {new['id']}"
        assert old.keys() == new.keys(), f"keys changed on id={old['id']}"
        for key in old:
            if key not in TEXT_FIELDS:
                assert old[key] == new[key], f"{key} changed on id={old['id']}"


def main():
    sources = sorted(OUTPUTS.glob("extracted_text_*.json"))
    corpus = {path: json.loads(path.read_text(encoding="utf-8")) for path in sources}

    # Boilerplate is collected across every file: the same company blurb shows
    # up in postings that landed in different files.
    texts = [
        record[field]
        for records in corpus.values()
        for record in records
        for field in TEXT_FIELDS
        if isinstance(record.get(field), str)
    ]
    boilerplate = collect_boilerplate(texts)
    print(f"corpus: {len(texts)} text fields, {len(boilerplate)} boilerplate lines found\n")

    for path, records in corpus.items():
        processed = process_records(records, boilerplate)
        check_structure(records, processed)

        destination = path.with_name(path.name.replace("extracted_text_", "cleaned_"))
        destination.write_text(
            json.dumps(processed, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        field = next(f for f in TEXT_FIELDS if isinstance(records[0].get(f), str))
        before = sum(len(r[f]) for r in records for f in TEXT_FIELDS if isinstance(r.get(f), str))
        after = sum(len(r[f]) for r in processed for f in TEXT_FIELDS if isinstance(r.get(f), str))

        print("=" * 78)
        print(f"{path.name}  ->  {destination.name}")
        print(f"{len(records)} records, id kept, structure identical")
        print(f"text {before} -> {after} chars ({100 - after * 100 // before}% removed)")
        print(f"\nBEFORE  id={records[0]['id']}  {field}:\n  {preview(records[0][field])}")
        print(f"\nAFTER   id={processed[0]['id']}  {field}:\n  {preview(processed[0][field])}\n")


if __name__ == "__main__":
    main()
