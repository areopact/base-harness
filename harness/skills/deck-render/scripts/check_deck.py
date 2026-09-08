#!/usr/bin/env python3
"""Static checks for a web-deck bundle.

Usage: python check_deck.py <deck-dir>/index.html
"""

from __future__ import annotations

import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse


KNOWN_LAYOUTS = {
    "cover", "statement", "split", "image", "gallery", "grid",
    "comparison", "data", "timeline", "quote", "document", "toc",
    "interactive", "appendix", "closing",
}


class DeckParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.slides: list[dict[str, str]] = []
        self.ids: list[str] = []
        self.assets: list[tuple[str, str]] = []
        self.indicators = 0
        self.bar_values: list[str] = []
        self.ring_values: list[str] = []
        self.jump_targets: list[str] = []
        self.demo_dwells: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = {key: value or "" for key, value in attrs}
        classes = set(data.get("class", "").split())
        element_id = data.get("id", "")
        if element_id:
            self.ids.append(element_id)
        if tag == "section" and "slide" in classes:
            self.slides.append(data)
            if "data-demo-loop" in data:
                self.demo_dwells.append(data["data-demo-loop"])
        if "page-indicator" in classes:
            self.indicators += 1
        if "data-value" in data:
            self.bar_values.append(data["data-value"])
        if "data-ring" in data:
            self.ring_values.append(data["data-ring"])
        if "data-jump" in data:
            self.jump_targets.append(data["data-jump"])
        if tag in {"script", "img", "video", "source"} and data.get("src"):
            self.assets.append((tag, data["src"]))
        if tag == "link" and data.get("href"):
            self.assets.append((tag, data["href"]))


def is_remote(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} or value.startswith("//")


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] in {"-h", "--help"}:
        print("usage: python check_deck.py <deck-dir>/index.html")
        return 2

    index = Path(sys.argv[1]).resolve()
    if not index.is_file():
        print(f"[x] deck not found: {index}")
        return 2

    source = index.read_text(encoding="utf-8-sig")
    parser = DeckParser()
    parser.feed(source)
    errors: list[str] = []
    warnings: list[str] = []

    if not parser.slides:
        errors.append("no <section class=\"slide\"> elements")
    if parser.indicators != 1:
        errors.append(f"expected one .page-indicator, found {parser.indicators}")
    indicator_match = re.search(
        r'<[^>]*class=["\'][^"\']*\bpage-indicator\b[^"\']*["\'][^>]*>([^<]*)<',
        source,
        re.I,
    )
    if not indicator_match or not re.fullmatch(r"\s*\d+\s*", indicator_match.group(1)):
        errors.append("page indicator must contain only the current number")
    if "data-page-label" in source:
        errors.append("deck must not declare a visible page label")

    duplicates = sorted({item for item in parser.ids if parser.ids.count(item) > 1})
    if duplicates:
        errors.append("duplicate ids: " + ", ".join(duplicates))

    for number, slide in enumerate(parser.slides, 1):
        if not slide.get("id"):
            errors.append(f"slide {number}: missing id")
        layout = slide.get("data-layout")
        if layout not in KNOWN_LAYOUTS:
            errors.append(f"slide {number}: unknown or missing data-layout {layout!r}")

    if len(parser.slides) > 20:
        if len(parser.slides) < 2 or parser.slides[1].get("data-layout") != "toc":
            errors.append("decks longer than 20 slides need a toc slide immediately after the cover")
        missing_sections = [
            str(number)
            for number, slide in enumerate(parser.slides, 1)
            if not slide.get("data-section", "").strip()
        ]
        if missing_sections:
            errors.append("long deck slides missing data-section: " + ", ".join(missing_sections))
        if len(set(parser.jump_targets)) < len(parser.slides) - 2:
            errors.append("long deck toc must list each page after the cover and contents slide")

    for raw in parser.demo_dwells:
        try:
            dwell = int(raw)
        except ValueError:
            errors.append(f"data-demo-loop is not an integer dwell: {raw!r}")
            continue
        if dwell != 500:
            errors.append(f"data-demo-loop must use the 500ms catalog dwell: {raw!r}")

    for raw in parser.bar_values:
        try:
            value = float(raw)
        except ValueError:
            errors.append(f"data-value is not numeric: {raw!r}")
            continue
        if not 0 <= value <= 100:
            errors.append(f"data-value outside 0..100: {raw!r}")

    for raw in parser.ring_values:
        try:
            value = float(raw)
        except ValueError:
            errors.append(f"data-ring is not numeric: {raw!r}")
            continue
        if not 0 <= value <= 100:
            errors.append(f"data-ring outside 0..100: {raw!r}")

    for tag, value in parser.assets:
        if value.startswith(("data:", "#", "mailto:", "tel:")):
            continue
        if is_remote(value):
            warnings.append(f"remote {tag} asset: {value}")
            continue
        local = (index.parent / value.split("?", 1)[0].split("#", 1)[0]).resolve()
        if not local.is_file():
            errors.append(f"missing local {tag} asset: {value}")

    css_paths = [
        (index.parent / value).resolve()
        for tag, value in parser.assets
        if tag == "link" and not is_remote(value) and value.lower().endswith(".css")
    ]
    css = "\n".join(path.read_text(encoding="utf-8-sig") for path in css_paths if path.is_file())

    # Measure caps: a ch-based max-width on display type is almost always a body-prose
    # number copied onto a headline. One ch is the element's own "0" advance width, so the
    # same value is a different physical width per typeface and size, and the cap then
    # forces a wrap while the container still has room.
    # See ./references/design-system.md, "Measure caps".
    authored_css = css + "\n" + "\n".join(
        re.findall(r"<style[^>]*>(.*?)</style>", source, re.S | re.I)
    )
    display_selector = re.compile(
        r"(?:\bh1\b|\bh2\b|\.[\w-]*(?:title|headline|display|eyebrow)[\w-]*)", re.I
    )
    for rule in re.finditer(r"([^{}]+)\{([^{}]*)\}", authored_css):
        selector, body = rule.group(1).strip(), rule.group(2)
        cap = re.search(r"max-width\s*:\s*([\d.]+)ch", body)
        if cap and display_selector.search(selector):
            warnings.append(
                "character-based measure cap on display type: "
                + selector
                + " { max-width: "
                + cap.group(1)
                + "ch } (ch is font-relative; bound headlines by their container "
                + "and derive any cap from a render)"
            )

    if not re.search(r"aspect-ratio\s*:\s*16\s*/\s*9", css):
        errors.append("runtime CSS does not declare a 16:9 stage")
    if not re.search(r"\.page-indicator\s*\{[^}]*right\s*:[^;}]+;[^}]*bottom\s*:", css, re.S):
        errors.append("page indicator is not anchored bottom-right in runtime CSS")
    if "prefers-reduced-motion: reduce" not in css:
        errors.append("runtime CSS does not handle prefers-reduced-motion")

    script_paths = [
        (index.parent / value).resolve()
        for tag, value in parser.assets
        if tag == "script" and not is_remote(value) and value.lower().endswith(".js")
    ]
    scripts = "\n".join(path.read_text(encoding="utf-8-sig") for path in script_paths if path.is_file())
    if "window.webDeckQA" not in scripts:
        errors.append("runtime does not expose window.webDeckQA()")
    if len(parser.slides) > 20 and "deck-map" not in scripts:
        errors.append("long-deck runtime does not provide the hidden chapter map")

    for warning in warnings:
        print(f"[!] {warning}")
    for error in errors:
        print(f"[x] {error}")
    if errors:
        print(f"FAIL: {len(errors)} error(s), {len(warnings)} warning(s)")
        return 1

    print(f"PASS: {len(parser.slides)} slides, 16:9 runtime, one current-only indicator hook, {len(warnings)} warning(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
