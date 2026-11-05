"""HTML tag mappings into the unchanged MainText canonical extraction."""

from .web import MainText


class StructuredText(MainText):
    def __init__(self):
        super().__init__()
        self.lengths = {"parts": 0, "main": 0}
        self.regions, self.open_regions, self.tables = [], [], []
        self.row, self.cell = None, None

    def append(self, value):
        if not self.skip:
            self.lengths["parts"] += len(value)
            if self.main_depth:
                self.lengths["main"] += len(value)
        super().append(value)

    def position(self):
        stream = "main" if self.main_depth else "parts"
        return stream, self.lengths[stream]

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        super().handle_starttag(tag, attrs)
        if self.skip:
            return
        stream, start = self.position()
        labels = (attributes.get("class", "") + " " + attributes.get("id", "")).lower()
        kind = (
            "definition"
            if "definition" in labels
            else "theorem"
            if any(k in labels for k in ("theorem", "lemma", "proposition"))
            else "heading"
            if tag in {"h1", "h2", "h3", "h4"}
            else None
        )
        if kind:
            self.open_regions.append({"tag": tag, "stream": stream, "kind": kind, "start": start})
        if tag == "table":
            self.tables.append({"headers": [], "available": True})
            if len(self.tables) > 1:
                for table in self.tables:
                    table["available"] = False
        if tag == "tr" and self.tables:
            self.row = {"stream": stream, "start": start, "cells": [], "kind": "table_row"}
        if tag in {"th", "td"} and self.row:
            if attributes.get("colspan", "1") != "1" or attributes.get("rowspan", "1") != "1":
                self.tables[-1]["available"] = False
            self.cell = {"start": start, "header": tag == "th"}

    def handle_endtag(self, tag):
        stream, end = self.position()
        if self.open_regions and self.open_regions[-1]["tag"] == tag:
            self.regions.append({**self.open_regions.pop(), "end": end})
        if tag in {"th", "td"} and self.row is not None and self.cell is not None:
            self.row["cells"].append({**self.cell, "end": end})
            self.cell = None
        if tag == "tr" and self.row is not None:
            row, table = {**self.row, "end": end}, self.tables[-1]
            if row["cells"] and all(c["header"] for c in row["cells"]):
                table["headers"] = row["cells"]
            if table["available"] and len(table["headers"]) == len(row["cells"]):
                row["headers"] = table["headers"]
                row["header_status"] = "mapped"
            else:
                row["header_status"] = "unavailable"
            self.regions.append(row)
            self.row = None
        if tag == "table" and self.tables:
            self.tables.pop()
        super().handle_endtag(tag)

    @property
    def structures(self):
        stream = "main" if self.main else "parts"
        result = []
        for region in self.regions:
            if region["stream"] != stream or region["start"] >= region["end"]:
                continue
            view = {k: v for k, v in region.items() if k not in {"stream", "tag"}}
            if "headers" in view:
                view["headers"] = [
                    {**h, "text": self.text[h["start"] : h["end"]]} for h in view["headers"]
                ]
            result.append(view)
        return result
