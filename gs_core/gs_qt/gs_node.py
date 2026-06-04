from __future__ import annotations


class GsNode:
    def __init__(self, name: str, path: str):
        self.name = name
        self.path = path

    def __repr__(self) -> str:
        return f"GsNode({self.name!r})"
