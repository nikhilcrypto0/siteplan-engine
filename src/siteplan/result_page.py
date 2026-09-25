"""One page per run, opened in the architect's browser as soon as the layouts are drawn.

The drawings already exist as SVG next to the DXF; this only arranges them side by side
with the computed comparison, so nobody has to go hunting in a folder.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title><style>
body {{ font: 15px/1.55 -apple-system, Helvetica, Arial, sans-serif; margin: 0;
  padding: 28px 16px; background: #fbfbf8; color: #1a1a1a; }}
main {{ max-width: 1180px; margin: 0 auto; }}
h1 {{ font-size: 21px; margin: 0 0 4px; }}
p.sub {{ color: #666; margin: 0 0 18px; }}
pre.compare {{ background: #fff; border: 1px solid #e3e3dd; border-radius: 10px;
  padding: 16px; white-space: pre-wrap; margin: 0 0 24px; }}
.options {{ display: grid; gap: 18px;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); }}
figure {{ margin: 0; background: #fff; border: 1px solid #e3e3dd; border-radius: 10px;
  padding: 14px; }}
figure img {{ width: 100%; height: auto; border: 1px solid #f0f0ea; border-radius: 6px; }}
figcaption {{ margin-top: 10px; font-size: 14px; }}
.fail {{ color: #a3200b; font-weight: 600; }}
.files a {{ color: #1f5f9f; }}
p.caveat {{ color: #7a5a1a; background: #fff8e8; border: 1px solid #f0e3c0;
  border-radius: 8px; padding: 12px; margin-top: 24px; font-size: 14px; }}
</style></head><body><main>
<h1>{title}</h1>
<p class="sub">{subtitle}</p>
<pre class="compare">{comparison}</pre>
<div class="options">{cards}</div>
<p class="caveat">{caveat}</p>
</main></body></html>"""

CARD = """<figure>
<img src="{svg}" alt="Option {option}">
<figcaption><strong>Option {option}</strong>: {towers}, {flats} flats, {sqft} sft saleable,
{built_up} sft built-up, open space {open_pct}%<br>{verdict}<br>
<span class="files"><a href="{dxf}">option_{option}.dxf</a> for ZWCAD ·
<a href="{sheet}">option_{option}.sheet.dxf</a> drawing sheet</span></figcaption>
</figure>"""


def write_result_page(record: dict, comparison: str, out: Path) -> Path:
    """Write index.html beside the drawings and return its path."""
    cards = []
    for option in record["options"]:
        n = option["option"]
        fails = [rule for rule, status in option["rule_findings"].items() if status == "FAIL"]
        verdict = (f'<span class="fail">FAILS {escape(", ".join(fails))}</span>'
                   if fails else "No rule failures")
        towers = f"{option['towers']} tower" + ("" if option["towers"] == 1 else "s")
        cards.append(CARD.format(
            option=n, svg=f"option_{n}.svg", dxf=f"option_{n}.dxf",
            sheet=f"option_{n}.sheet.dxf", towers=towers,
            flats=option["total_flats"], sqft=f"{option['saleable_sqft']:,}",
            built_up=f"{option.get('built_up_sqft', 0):,}",
            open_pct=option["open_space_share_pct"], verdict=verdict,
        ))
    page = PAGE.format(
        title=escape(record["project"]),
        subtitle=escape(f"{record['plot']} · brief: {record['brief']}"),
        comparison=escape(comparison),
        cards="".join(cards),
        caveat=escape(f"{record['caveat']} {record['flat_library_note']}"),
    )
    path = out / "index.html"
    path.write_text(page)
    return path
