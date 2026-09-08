#!/usr/bin/env python
"""Fold a web-deck bundle (index.html + deck.css + deck.js + media) into one self-contained HTML file.

Needed for hosts that serve one HTML document per slug.
Inlines local <link rel="stylesheet" href> and <script src> files, and converts local <img src>,
<source src>, poster and CSS url(...) references into data: URIs. Remote (http, https, data) references
are left untouched.

Usage: python inline_bundle.py <deck-dir> <out.html>
"""
import base64
import mimetypes
import os
import re
import sys

if len(sys.argv) != 3 or sys.argv[1] in {"-h", "--help"}:
    print("Usage: python inline_bundle.py <deck-dir> <out.html>", file=sys.stderr)
    sys.exit(2)
deck, out = sys.argv[1], sys.argv[2]
html = open(os.path.join(deck, "index.html"), encoding="utf-8").read()
REMOTE = re.compile(r"^(https?:|data:|//|#|mailto:)", re.I)


def local(path):
    return not REMOTE.match(path.strip())


def data_uri(path):
    p = os.path.normpath(os.path.join(deck, path.split("?")[0].split("#")[0]))
    if not os.path.isfile(p):
        return None
    mime = mimetypes.guess_type(p)[0] or "application/octet-stream"
    return "data:%s;base64,%s" % (mime, base64.b64encode(open(p, "rb").read()).decode())


def inline_css_urls(css, base):
    def rep(m):
        ref = m.group(2)
        if not local(ref):
            return m.group(0)
        d = data_uri(os.path.join(base, ref))
        return "url(%s)" % d if d else m.group(0)
    return re.sub(r"url\((['\"]?)([^'\")]+)\1\)", rep, css)


def rep_link(m):
    href = m.group(1)
    if not local(href):
        return m.group(0)
    p = os.path.join(deck, href)
    if not os.path.isfile(p):
        return m.group(0)
    css = inline_css_urls(open(p, encoding="utf-8").read(), os.path.dirname(href))
    return "<style>\n%s\n</style>" % css


def rep_script(m):
    before, src, after = m.group(1) or "", m.group(2), m.group(3) or ""
    if not local(src):
        return m.group(0)
    p = os.path.join(deck, src)
    if not os.path.isfile(p):
        return m.group(0)
    js = open(p, encoding="utf-8").read().replace("</script>", "<\\/script>")
    attrs = (before + " " + after).strip()
    opening = "<script %s>" % attrs if attrs else "<script>"
    return "%s\n%s\n</script>" % (opening, js)


def rep_src(m):
    attr, src = m.group(1), m.group(2)
    if not local(src):
        return m.group(0)
    d = data_uri(src)
    return '%s="%s"' % (attr, d) if d else m.group(0)


html = re.sub(r'<link[^>]+rel=["\']stylesheet["\'][^>]*href=["\']([^"\']+)["\'][^>]*>', rep_link, html, flags=re.I)
html = re.sub(r'<script([^>]*?)\s*src=["\']([^"\']+)["\']([^>]*)>\s*</script>', rep_script, html, flags=re.I)
html = re.sub(r'\b(src|poster)=["\']([^"\']+)["\']', rep_src, html, flags=re.I)
html = re.sub(r"<style>(.*?)</style>", lambda m: "<style>%s</style>" % inline_css_urls(m.group(1), ""), html, flags=re.S | re.I)

os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
open(out, "w", encoding="utf-8", newline="\n").write(html)
left = len(re.findall(r'(?:href|src)=["\'](?!https?:|data:|#|//)', html))
print("[ok] %s: %s bytes; remaining local refs: %d" % (out, format(len(html), ","), left))
