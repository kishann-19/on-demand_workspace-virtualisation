"""Inline local CSS/JS so static websites can run in an opaque-origin iframe."""

from html import escape
from html.parser import HTMLParser
from urllib.parse import urlsplit


class PreviewBuilder(HTMLParser):
    def __init__(self, read):
        super().__init__(convert_charrefs=False)
        self.read = read
        self.output = []
        self.external_script = False

    def local(self, path):
        parsed = urlsplit(path)
        if parsed.scheme or parsed.netloc:
            raise ValueError("Preview only supports local assets.")
        return self.read(parsed.path.lstrip("/"))

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == "link" and attrs.get("rel") == "stylesheet" and attrs.get("href"):
            content = self.local(attrs["href"]).replace("</style", "<\\/style")
            self.output.append(f"<style>{content}</style>")
        elif tag == "script" and attrs.get("src"):
            content = self.local(attrs["src"]).replace("</script", "<\\/script")
            self.output.append(f"<script>{content}</script>")
            self.external_script = True
        else:
            self.output.append(self.get_starttag_text())

    def handle_endtag(self, tag):
        if tag == "script" and self.external_script:
            self.external_script = False
        else:
            self.output.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.external_script:
            self.output.append(data)

    def handle_entityref(self, name):
        self.output.append(f"&{name};")

    def handle_charref(self, name):
        self.output.append(f"&#{name};")

    def handle_comment(self, data):
        self.output.append(f"<!--{data}-->")

    def handle_decl(self, decl):
        self.output.append(f"<!{decl}>")


def build_preview(read):
    parser = PreviewBuilder(read)
    try:
        parser.feed(read("index.html"))
        parser.close()
        return "".join(parser.output)
    except ValueError as exc:
        return f"<h1>Preview unavailable</h1><p>{escape(str(exc))}</p>"
