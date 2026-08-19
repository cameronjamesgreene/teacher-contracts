# Legacy salary extractor (v12)

Frozen copies of the model-transcription salary path, kept because it is still the
only thing that extracts **scanned** documents.

| file | origin |
|---|---|
| `salary_schedule_v12.py` | `scripts/salary_schedule.py` at commit 3fa11d0 |
| `salary_segment_v12.py`  | `scripts/salary_segment.py` |
| `salary_navigate_v12.py` | `scripts/salary_navigate.py` |

## Why it is kept rather than retired

The replacement (`scripts/salary_geometry.py`) reads PDF word coordinates, and Pittsburgh,
Fresno and NYC have **zero vector words on every page** — they are pure scans. No OCR
engine available on the Yale HPC emits per-word bounding boxes: olmOCR-2 returns markdown
text, and Apple Vision is macOS-only and returns per-LINE boxes. Geometry therefore cannot
reach these documents at all.

This path can, because it sends a rendered page IMAGE to the SOM API — an API call, so it
runs on the HPC — and because `_vision_extract_rotated` handles Pittsburgh's salary pages,
which are printed sideways (123 of 130 OCR observations on p16 are taller than wide).

Do not edit these files. `scripts/build_salary_long.py` consumes the wide CSVs they
produced under `output/output_v12/salary_schedule_wide/`.
