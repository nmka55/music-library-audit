"""Interactive, conservative review of REVIEW match candidates."""

import json
import os
from pathlib import Path


def _save(path, overrides):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(dict(sorted(overrides.items())), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def review_matches(apple, matches, overrides, override_path, offline=None, ask=input, tell=print):
    """Review each REVIEW row; no rejects only the current candidate.

    Confirmed choices are saved immediately. If all candidates are rejected,
    the entry remains REVIEW because the program must not guess MISSING.
    """
    review_rows = [row for row in matches if row.get("Status") == "REVIEW"]
    if not review_rows:
        tell("There are no REVIEW entries.")
        return matches, overrides
    tell(f"Interactive review: {len(review_rows):,} REVIEW entries.")
    tell("Answer yes to confirm, no to try the next candidate, or quit to stop.")
    by_pid = {row.get("Apple Persistent ID"): row for row in apple}
    by_path = {os.path.normcase(os.path.abspath(row["Full Path"])): row for row in (offline or [])}
    decisions = 0
    for position, result in enumerate(review_rows, 1):
        pid = result.get("Apple Persistent ID")
        apple_row = by_pid.get(pid, {})
        candidates = []
        for key in (
            "Matched File Path",
            "Alternative Candidate 1",
            "Alternative Candidate 2",
            "Alternative Candidate 3",
        ):
            candidate = result.get(key)
            if candidate and candidate not in candidates:
                candidates.append(candidate)
        tell("")
        tell(f"[{position}/{len(review_rows)}] Apple Music track")
        tell(f"  Title: {apple_row.get('Name', result.get('Apple Title', ''))}")
        tell(f"  Artist: {apple_row.get('Artist', result.get('Apple Artist', ''))}")
        tell(f"  Album: {apple_row.get('Album', result.get('Apple Album', ''))}")
        tell(f"  Duration: {result.get('Apple Duration')} seconds")
        tell(f"  Reason: {result.get('Match Reason', '')}")
        if not candidates:
            tell("  No candidate was retained; this entry remains REVIEW.")
            continue
        confirmed = False
        for candidate_number, candidate in enumerate(candidates, 1):
            while True:
                tell(f"  Candidate {candidate_number}: {candidate}")
                answer = ask("  Is this the same recording? [yes/no/quit]: ").strip().casefold()
                if answer in {"q", "quit", "exit"}:
                    tell("Review stopped. Confirmed decisions were already saved.")
                    return matches, overrides
                if answer in {"y", "yes"}:
                    overrides[pid] = candidate
                    _save(override_path, overrides)
                    result.update(
                        {
                            "Status": "MATCHED",
                            "Match Type": "MANUAL MATCH",
                            "Overall Confidence": 100,
                            "Matched File Path": candidate,
                            "Review Notes": "Confirmed interactively by the user; saved as a manual override",
                            "Match Reason": "MANUAL MATCH: user confirmed the candidate during interactive review",
                        }
                    )
                    selected = by_path.get(os.path.normcase(os.path.abspath(candidate)))
                    if selected:
                        result.update(
                            {
                                "Matched Offline Title": selected.get("Title"),
                                "Matched Offline Artist": selected.get("Artist"),
                                "Matched Offline Album": selected.get("Album"),
                                "Offline Duration": selected.get("Duration"),
                                "Library Root": selected.get("Library Root"),
                                "Archive Eligible": selected.get("Archive Eligible", False),
                                "Integrity": selected.get("Integrity"),
                                "Metadata Quality": selected.get("Metadata Issues") or "GOOD",
                                "Artwork": selected.get("Artwork Present", False),
                                "Duration Difference": abs(
                                    (result.get("Apple Duration") or 0)
                                    - (selected.get("Duration") or 0)
                                ),
                            }
                        )
                    confirmed = True
                    decisions += 1
                    tell("  Confirmed and saved.")
                    break
                if answer in {"n", "no"}:
                    break
                tell("  Please answer yes, no, or quit.")
            if confirmed:
                break
        if not confirmed:
            tell("  No candidate confirmed; this entry remains REVIEW.")
    tell(
        f"Interactive review complete: {decisions:,} confirmed; {sum(row.get('Status') == 'REVIEW' for row in matches):,} remain REVIEW."
    )
    return matches, overrides
