import os
import re
from typing import Dict, List, Optional
import xml.etree.ElementTree as ET

from .git_aware_code_indexer import Chunk, Range, ChunkPlugin, PayloadPlugin, sha256


def _safe_parse_xml(src: str) -> Optional[ET.Element]:
    try:
        return ET.fromstring(src)
    except ET.ParseError:
        return None


def _first_n(text: str, n: int = 800) -> str:
    return text[:n]


class AndroidChunkPlugin(ChunkPlugin):
    """Android-aware chunk plugin that can add synthetic chunks for nav/layout XML."""

    def supports(self, path: str, stack_type: Optional[str] = None) -> bool:
        if stack_type and stack_type != "android_app":
            return False
        return os.path.splitext(path)[1].lower() == ".xml" and (
            "/res/layout/" in path or "/res/navigation/" in path or path.endswith("AndroidManifest.xml")
        )

    def preprocess(self, src: str, path: str, repo: str) -> str:
        # Keep XML as-is; hook reserved for normalization.
        return src

    def postprocess(self, chunks: List[Chunk], path: str, repo: str) -> List[Chunk]:
        return chunks

    def extra_chunks(self, src: str, path: str, repo: str) -> List[Chunk]:
        if not self.supports(path, "android_app"):
            return []
        meta = self._extract_meta(src, path)
        if not meta:
            return []
        # Create a lightweight synthetic chunk summarizing the XML content.
        content = meta["summary"]
        content_hash = sha256(content.encode())
        lines = content.count("\n") + 1
        symbol = f"android:{meta['kind']}:{meta['name']}"
        logical_id = f"{repo}:{path}#{symbol}"
        return [
            Chunk(
                logical_id=logical_id,
                symbol=symbol,
                path=path,
                language="xml",
                range=Range(1, lines, 0, len(content.encode())),
                content=content,
                content_hash=content_hash,
                sig_hash=sha256(symbol.encode()),
            )
        ]

    def _extract_meta(self, src: str, path: str) -> Optional[Dict[str, str]]:
        root = _safe_parse_xml(src)
        if root is None:
            return None
        kind = "xml"
        name = os.path.basename(path)
        if path.endswith("AndroidManifest.xml"):
            kind = "manifest"
            app_name = root.attrib.get("{http://schemas.android.com/apk/res/android}name") or "app"
            name = app_name
        elif "/res/layout/" in path:
            kind = "layout"
            name = os.path.splitext(os.path.basename(path))[0]
        elif "/res/navigation/" in path:
            kind = "navgraph"
            name = os.path.splitext(os.path.basename(path))[0]
        summary_lines = [f"<{root.tag} ... />"]
        if kind == "navgraph":
            destinations = [node.attrib.get("{http://schemas.android.com/apk/res/android}id", "") for node in root]
            destinations = [d for d in destinations if d]
            if destinations:
                summary_lines.append("destinations: " + ", ".join(destinations))
        return {"kind": kind, "name": name, "summary": "\n".join(summary_lines)}


class AndroidPayloadPlugin(PayloadPlugin):
    """Attach Android-specific metadata to chunk payloads."""

    def __init__(self, stack_type: str = "android_app"):
        self.stack_type = stack_type

    def build_payload(self, chunk: Chunk, branch: str, commit_sha: str) -> Dict[str, Optional[str]]:
        payload: Dict[str, Optional[str]] = {"stack_type": self.stack_type}

        # Basic heuristics by path/symbol.
        path = chunk.path
        tags: List[str] = []

        if path.endswith("AndroidManifest.xml"):
            payload["component_type"] = "manifest"
            tags.append("manifest")
        if "/res/layout/" in path:
            layout_name = os.path.splitext(os.path.basename(path))[0]
            payload["layout_file"] = layout_name
            payload["screen_name"] = payload.get("screen_name") or layout_name
            tags.append("layout")
        if "/res/navigation/" in path:
            nav_id = os.path.splitext(os.path.basename(path))[0]
            payload["nav_graph_id"] = nav_id
            tags.append("navgraph")

        symbol = chunk.symbol.lower()
        if symbol.startswith("class:"):
            class_name = symbol.split(":", 1)[1]
            if class_name.endswith("activity"):
                payload["component_type"] = payload.get("component_type") or "activity"
            if class_name.endswith("fragment"):
                payload["component_type"] = payload.get("component_type") or "fragment"
            payload["screen_name"] = payload.get("screen_name") or class_name

        if tags:
            payload["tags"] = sorted(set(tags))

        # Do not bloat payload when heuristics find nothing beyond stack_type.
        return {k: v for k, v in payload.items() if v is not None}
