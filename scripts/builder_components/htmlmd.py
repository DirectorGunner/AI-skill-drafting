"""HTML -> Markdown conversion (was the htmlmd.py section of skill_builder.py)."""

from __future__ import annotations

import html
import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin


# ==============================================================================
# SHARED — HTML -> Markdown (was htmlmd.py)
# ==============================================================================

_SKIP = {"script", "style", "head", "nav", "header", "footer", "aside", "noscript", "svg", "button", "form"}
_BLOCK = {"p", "div", "section", "article", "ul", "ol", "li", "pre", "blockquote", "table",
          "tr", "thead", "tbody", "h1", "h2", "h3", "h4", "h5", "h6", "hr"}


class _MD(HTMLParser):
    """Streaming HTML parser that emits Markdown, collecting headings and tables as it goes."""

    def __init__(self, base_url: str = ""):
        """Initialize parser state; base_url resolves relative link/image hrefs."""
        super().__init__(convert_charrefs=True)
        self.base = base_url
        self.out: list[str] = []
        self.skip_depth = 0
        self.pre_depth = 0          # inside <pre> (code block)
        self.code_inline = 0        # inside inline <code> (not in pre)
        self.pre_lang = ""
        self.list_stack: list[str] = []   # 'ul'/'ol' with counters
        self.ol_counters: list[int] = []
        self.href: str | None = None
        self.link_text: list[str] = []
        self.in_table = False
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.table_rows: list[list[str]] = []
        self.table_header_done = False
        self.headings: list[tuple[int, str, str]] = []   # (level, text, id) for callers
        self._cur_id = ""
        self._cur_h: list | None = None
        self._a_class = ""          # class of the anchor currently open (to drop ¶ headerlinks)

    # ---- helpers ----
    def _emit(self, s: str):
        """Append text to the current sink: open table cell, open link text, or main output."""
        if self.cell is not None:
            self.cell.append(s)
        elif self.link_text and self.href is not None:
            self.link_text.append(s)
        else:
            self.out.append(s)

    def _nl(self, n=1):
        """Emit n newlines to the main output, but only when not inside a cell or link text."""
        if self.cell is None and not (self.link_text and self.href is not None):
            self.out.append("\n" * n)

    # ---- tags ----
    def handle_starttag(self, tag, attrs):
        """Translate an opening HTML tag into its Markdown prefix and update parser state."""
        a = dict(attrs)
        if self.skip_depth or tag in _SKIP:
            if tag in _SKIP:
                self.skip_depth += 1
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            lvl = int(tag[1])
            self._nl(2)
            self._emit("#" * lvl + " ")
            self._cur_h = [lvl, [], a.get("id", "")]
            self._cur_id = a.get("id", "")
        elif tag == "p":
            self._nl(2)
        elif tag == "br":
            self._emit("  \n")
        elif tag == "hr":
            self._nl(2); self._emit("---"); self._nl(2)
        elif tag == "pre":
            if not self.pre_lang and "rust" in a.get("class", ""):
                self.pre_lang = "rust"   # rustdoc: <pre class="rust item-decl">
            self.pre_depth += 1
            self._nl(2); self._emit("```" + self.pre_lang); self._nl(1)
        elif tag == "code":
            cls = a.get("class", "")
            m = re.search(r"language-([\w+-]+)", cls) or re.search(r"\b(rust|python|bash|sh|json|toml|c|cpp|js|ts|html)\b", cls)
            if self.pre_depth:
                pass  # text captured verbatim
            else:
                self.code_inline += 1
                self._emit("`")
            if m and self.pre_depth:
                self.pre_lang = m.group(1)
        elif tag in ("strong", "b"):
            self._emit("**")
        elif tag in ("em", "i"):
            self._emit("*")
        elif tag == "a":
            if not self.pre_depth:   # inside a code fence, anchors emit their text only (clean signatures)
                self.href = a.get("href", "")
                self._a_class = a.get("class", "") or ""
                self.link_text = [""]
        elif tag == "dt":          # definition-list term (Sphinx API signature) -> own line
            self._nl(2)
        elif tag == "dd":          # definition body (the description) -> indented new line
            self._nl(1)
        elif tag == "div":         # Sphinx code wrapper carries the language: highlight-<lang>
            cls = a.get("class", "")
            m = re.search(r"highlight-(\w+)", cls)
            if m:
                lang = m.group(1).lower()
                self.pre_lang = {"default": "python", "python3": "python", "ipython3": "python",
                                 "pycon": "pycon", "pycon3": "pycon", "py": "python"}.get(lang, lang)
        elif tag == "ul":
            self.list_stack.append("ul"); self.ol_counters.append(0)
        elif tag == "ol":
            self.list_stack.append("ol"); self.ol_counters.append(0)
        elif tag == "li":
            self._nl(1)
            indent = "  " * (len(self.list_stack) - 1)
            if self.list_stack and self.list_stack[-1] == "ol":
                self.ol_counters[-1] += 1
                self._emit(f"{indent}{self.ol_counters[-1]}. ")
            else:
                self._emit(f"{indent}- ")
        elif tag == "blockquote":
            self._nl(2); self._emit("> ")
        elif tag == "table":
            self.in_table = True; self.table_rows = []; self.table_header_done = False
        elif tag == "tr":
            self.row = []
        elif tag in ("td", "th"):
            self.cell = []
        elif tag == "img":
            alt = a.get("alt", "").strip()
            src = a.get("src", "")
            cap = alt or re.sub(r"[-_]+", " ", re.sub(r"\.[a-z0-9]+$", "", src.rsplit("/", 1)[-1], flags=re.I))
            self._emit(f"(Figure: {cap})")

    def handle_endtag(self, tag):
        """Translate a closing HTML tag into its Markdown suffix and finalize state (links, tables)."""
        if tag in _SKIP and self.skip_depth:
            self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            if self._cur_h:
                txt = "".join(self._cur_h[1]).replace("​", "").strip()
                self.headings.append((self._cur_h[0], txt, self._cur_h[2]))
                self._cur_h = None
            self._nl(2)
        elif tag == "pre":
            if self.pre_depth:
                self.pre_depth -= 1
                self._nl(1); self._emit("```"); self._nl(2); self.pre_lang = ""
        elif tag == "code" and not self.pre_depth and self.code_inline:
            self.code_inline -= 1; self._emit("`")
        elif tag in ("strong", "b"):
            self._emit("**")
        elif tag in ("em", "i"):
            self._emit("*")
        elif tag == "a":
            if self.href is None:   # no open link (e.g. an anchor inside <pre>): text already emitted verbatim
                self._a_class = ""; self.link_text = []
            else:
                text = "".join(self.link_text).strip()
                href = self.href; acls = self._a_class
                self.href = None; self.link_text = []; self._a_class = ""
                if "headerlink" in acls or text in ("¶", "#"):
                    pass  # Sphinx permalink pilcrow (¶) — drop it
                elif href and not href.startswith("#") and text:
                    url = urljoin(self.base, href) if self.base else href
                    self._emit(f"[{text}]({url})")
                else:
                    self._emit(text)
        elif tag in ("dt", "dd"):
            self._nl(1)
        elif tag in ("ul", "ol"):
            if self.list_stack:
                self.list_stack.pop(); self.ol_counters.pop()
            self._nl(1)
        elif tag in ("p", "blockquote"):
            self._nl(2)
        elif tag in ("td", "th"):
            if self.row is not None and self.cell is not None:
                self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr":
            if self.row is not None:
                self.table_rows.append(self.row); self.row = None
        elif tag == "table":
            self._flush_table(); self.in_table = False

    def handle_data(self, data):
        """Emit text content; verbatim inside <pre>, whitespace-collapsed elsewhere."""
        if self.skip_depth:
            return
        if self.pre_depth:
            self._emit(data)
            return
        text = data
        if self._cur_h is not None:
            self._cur_h[1].append(text)
        # collapse whitespace outside code/pre
        collapsed = re.sub(r"\s+", " ", text)
        if collapsed:
            self._emit(collapsed)

    def _flush_table(self):
        """Render the collected table rows as a padded GFM Markdown table into the output."""
        rows = [r for r in self.table_rows if r]
        if not rows:
            return
        self.out.append("\n")
        ncols = max(len(r) for r in rows)
        head = rows[0] + [""] * (ncols - len(rows[0]))
        self.out.append("| " + " | ".join(head) + " |\n")
        self.out.append("| " + " | ".join(["---"] * ncols) + " |\n")
        for r in rows[1:]:
            r = r + [""] * (ncols - len(r))
            self.out.append("| " + " | ".join(r) + " |\n")
        self.out.append("\n")


def _balanced_div_inner(html: str, open_match: "re.Match") -> str:
    """Given a match for an opening <div ...>, return its inner HTML up to the matching </div>
    (depth-balanced — handles the nested divs that a non-greedy regex would stop short on)."""
    start = open_match.end()
    depth = 1
    for m in re.finditer(r"<div\b|</div\s*>", html[start:], re.IGNORECASE):
        if m.group(0)[1] == "/":
            depth -= 1
            if depth == 0:
                return html[start:start + m.start()]
        else:
            depth += 1
    return html[start:]


def split_main(html: str) -> str:
    """Return the inner HTML of the doc body. Tries, in order: a div with role="main" (Sphinx),
    <main>, <div id="content">, <body>, else the whole document."""
    m = re.search(r'<div\b[^>]*\brole=["\']main["\'][^>]*>', html, re.IGNORECASE)
    if m:
        return _balanced_div_inner(html, m)
    for pat in (r"<main\b[^>]*>(.*?)</main>", r'<div[^>]*id="content"[^>]*>(.*?)</div>\s*</div>'):
        m = re.search(pat, html, re.DOTALL | re.IGNORECASE)
        if m:
            return m.group(1)
    m = re.search(r"<body\b[^>]*>(.*?)</body>", html, re.DOTALL | re.IGNORECASE)
    return m.group(1) if m else html


def html_to_md(html: str, base_url: str = "") -> tuple[str, list]:
    """Convert HTML to Markdown. Returns (markdown, headings) where headings is a list of
    (level, text, id). Pass the doc body (use split_main first for full pages)."""
    p = _MD(base_url)
    p.feed(html)
    md = "".join(p.out)
    md = unescape(md)
    md = md.replace("​", "")                  # strip zero-width-space anchor artifacts
    md = re.sub(r"(?m)^[ \t]*#{1,6}[ \t]*$", "", md)  # drop headings left empty after that
    md = re.sub(r"[ \t]+\n", "\n", md)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip() + "\n", p.headings
