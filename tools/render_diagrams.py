"""Render the editable diagram sources in docs/diagrams/*.html to PNG.

    .venv\\Scripts\\python.exe tools\\render_diagrams.py

Uses the installed Chrome with JavaScript off and every network request
blocked, so only the static SVG in each file is drawn.
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
DIAGRAMS = ROOT / "docs" / "diagrams"


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        context = browser.new_context(java_script_enabled=False, device_scale_factor=2)
        context.route("**/*", lambda route: route.continue_() if route.request.url.startswith("file:") else route.abort())
        page = context.new_page()
        for src in sorted(DIAGRAMS.glob("*.html")):
            page.goto(src.resolve().as_uri())
            svg = page.locator("svg").first
            box = svg.evaluate("el => [el.viewBox.baseVal.width, el.viewBox.baseVal.height]")
            page.set_viewport_size({"width": int(box[0]), "height": int(box[1])})
            out = src.with_suffix(".png")
            svg.screenshot(path=out)
            print(out.relative_to(ROOT))
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
