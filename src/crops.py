"""Evidence crops: the pixels a number actually came from.

Owns: cutting a small image around each parsed value and encoding it for
embedding in the dashboard.

Does NOT own: deciding which values need one.

This is what makes the dataset auditable. A number in a chart is an assertion;
a number next to the strip of scan it was read from is evidence. It is also
what makes human verification possible at all -- checking 400 values against
112 full pages is impractical, checking them against 400 thumbnails is not.
"""

from __future__ import annotations

import base64
import subprocess

from . import config as C

# Context around the value box, as a multiple of its own height. The value alone
# is unreadable out of context -- you cannot tell 34.3 for prothrombin time from
# 34.3 for anything else -- so the crop reaches left across the analyte name and
# right across the unit and reference range.
PAD_LEFT_FRAC = 0.30      # of page width, to include the test name column
PAD_RIGHT_FRAC = 0.45     # to include unit + reference interval
PAD_VERTICAL = 0.6        # of the box height, above and below


def crop_box(bbox, page_width: int, page_height: int) -> tuple[int, int, int, int]:
    x, y, w, h = bbox
    left = max(0, int(x - page_width * PAD_LEFT_FRAC))
    right = min(page_width, int(x + w + page_width * PAD_RIGHT_FRAC))
    top = max(0, int(y - h * PAD_VERTICAL))
    bottom = min(page_height, int(y + h * (1 + PAD_VERTICAL)))
    return left, top, max(1, right - left), max(1, bottom - top)


def make_crop(page_image, bbox, out_path, page_width: int, page_height: int,
              target_width: int = 620) -> bool:
    """Write one evidence crop. Returns False if the region is degenerate."""
    x, y, w, h = crop_box(bbox, page_width, page_height)
    if w < 20 or h < 8:
        return False
    out_path.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        [C.MAGICK, str(page_image), "-crop", f"{w}x{h}+{x}+{y}", "+repage",
         "-colorspace", "gray", "-normalize", "-resize", f"{target_width}x",
         "-quality", "78", str(out_path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode == 0 and out_path.exists()


def as_data_uri(path) -> str | None:
    """Base64 data URI, so the dashboard stays a single self-contained file."""
    if not path or not path.exists():
        return None
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")
