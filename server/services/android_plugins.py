import os
import re
from typing import Dict, List, Optional
import xml.etree.ElementTree as ET

from .git_aware_code_indexer import Chunk, Range, ChunkPlugin, PayloadPlugin, sha256
from .edges import EdgePayload, EdgeType, build_edge, dedupe_edges, merge_edges, normalize_id, normalize_layout_target

ANDROID_NS = "{http://schemas.android.com/apk/res/android}"
APP_NS = "{http://schemas.android.com/apk/res-auto}"


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
        return src

    def postprocess(self, chunks: List[Chunk], path: str, repo: str) -> List[Chunk]:
        return chunks

    def extra_chunks(self, src: str, path: str, repo: str) -> List[Chunk]:
        if not self.supports(path, "android_app"):
            return []
        meta = self._extract_meta(src, path)
        if not meta:
            return []
        content = meta.get("summary", "")
        content_hash = sha256(content.encode())
        lines = content.count("\n") + 1
        symbol = f"android:{meta.get('kind', 'xml')}:{meta.get('name') or os.path.basename(path)}"
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
                meta=meta,
            )
        ]

    def _extract_meta(self, src: str, path: str) -> Optional[Dict[str, object]]:
        root = _safe_parse_xml(src)
        if root is None:
            return None

        def _attr(node: ET.Element, name: str) -> Optional[str]:
            return node.attrib.get(f"{ANDROID_NS}{name}") or node.attrib.get(name)

        def _app_attr(node: ET.Element, name: str) -> Optional[str]:
            return node.attrib.get(f"{APP_NS}{name}") or node.attrib.get(name)

        kind = "xml"
        name = os.path.basename(path)
        summary_lines: List[str] = [f"<{root.tag} ... />"]
        meta: Dict[str, object] = {"kind": kind, "name": name}
        edges: List[EdgePayload] = []

        if path.endswith("AndroidManifest.xml"):
            kind = "manifest"
            pkg_name = root.attrib.get("package") or _attr(root, "name") or "app"
            name = pkg_name
            components = []
            for tag in ("activity", "activity-alias", "service", "receiver", "provider"):
                for node in root.findall(f".//{tag}"):
                    comp_name = _attr(node, "name")
                    if not comp_name:
                        continue
                    comp: Dict[str, object] = {"type": tag, "name": comp_name}
                    label = _attr(node, "label")
                    if label:
                        comp["label"] = label
                    actions = [_attr(action, "name") for action in node.findall(".//intent-filter/action") if _attr(action, "name")]
                    categories = [
                        _attr(cat, "name")
                        for cat in node.findall(".//intent-filter/category")
                        if _attr(cat, "name")
                    ]
                    if actions:
                        comp["actions"] = actions
                    if categories:
                        comp["categories"] = categories
                    components.append(comp)
            summary_lines = [f"manifest package={name}"]
            if components:
                summary_lines.extend(
                    [
                        f"{c['type']} {c['name']}"
                        + (f" actions={','.join(c['actions'])}" if c.get("actions") else "")
                        for c in components
                    ]
                )
            meta.update({"kind": kind, "name": name, "components": components})
        elif "/res/layout/" in path:
            kind = "layout"
            name = os.path.splitext(os.path.basename(path))[0]
            view_ids: List[str] = []
            fragment_tags: List[str] = []
            viewmodel_class: Optional[str] = None
            for node in root.iter():
                node_id = _attr(node, "id")
                if node_id:
                    parsed = normalize_id(node_id)
                    if parsed:
                        view_ids.append(parsed)
                frag_name = _attr(node, "name")
                if frag_name and node.tag.lower() == "fragment":
                    fragment_tags.append(frag_name)
                    frag_id = normalize_id(node_id)
                    if frag_id:
                        fragment_tags.append(frag_id)
            data_binding = root.find(".//variable")
            if data_binding is not None:
                viewmodel_class = data_binding.attrib.get("type")
            summary_lines = [f"layout {name}"]
            if view_ids:
                summary_lines.append("ids: " + ", ".join(sorted(set(view_ids))))
            if fragment_tags:
                summary_lines.append("fragments: " + ", ".join(sorted(set(fragment_tags))))
            if viewmodel_class:
                summary_lines.append(f"viewmodel: {viewmodel_class}")
            meta.update(
                {
                    "kind": kind,
                    "name": name,
                    "layout_file": name,
                    "view_ids": sorted(set(view_ids)),
                    "fragment_tags": sorted(set(fragment_tags)),
                    "viewmodel_class": viewmodel_class,
                }
            )
            if viewmodel_class:
                edges.append(build_edge(EdgeType.USES_VIEWMODEL, viewmodel_class))
        elif "/res/navigation/" in path:
            kind = "navgraph"
            name = os.path.splitext(os.path.basename(path))[0]
            nav_id = normalize_id(_attr(root, "id")) or name
            start_dest = normalize_id(_attr(root, "startDestination") or _app_attr(root, "startDestination"))
            destinations: List[str] = []
            actions: List[Dict[str, Optional[str]]] = []
            for node in root:
                dest_id = normalize_id(_attr(node, "id"))
                if dest_id:
                    destinations.append(dest_id)
                    edges.append(build_edge(EdgeType.NAV_DESTINATION, dest_id))
                for action in node.findall(".//action"):
                    target = normalize_id(_app_attr(action, "destination") or _attr(action, "destination"))
                    act_id = normalize_id(_attr(action, "id"))
                    if target:
                        actions.append({"id": act_id, "from": dest_id or node.tag, "to": target})
                        edges.append(
                            build_edge(EdgeType.NAV_ACTION, target, {"source": dest_id or node.tag, "id": act_id})
                        )
            summary_lines = [f"navgraph {nav_id}"]
            if start_dest:
                summary_lines.append(f"start: {start_dest}")
            if destinations:
                summary_lines.append("destinations: " + ", ".join(sorted(set(destinations))))
            if actions:
                action_summaries = [f"{a.get('from')}->{a.get('to')}" for a in actions]
                summary_lines.append("actions: " + ", ".join(action_summaries))
            meta.update(
                {
                    "kind": kind,
                    "name": name,
                    "nav_graph_id": nav_id,
                    "destinations": sorted(set(destinations)),
                    "actions": actions,
                    "edges": edges,
                    "start_destination": start_dest,
                }
            )
        meta["summary"] = "\n".join(summary_lines)
        if "kind" not in meta:
            meta["kind"] = kind
        if "name" not in meta:
            meta["name"] = name
        if edges:
            meta["edges"] = merge_edges(meta.get("edges", []), edges)
        return meta


class AndroidPayloadPlugin(PayloadPlugin):
    """Attach Android-specific metadata to chunk payloads."""

    def __init__(self, stack_type: str = "android_app"):
        self.stack_type = stack_type

    def build_payload(self, chunk: Chunk, branch: str, commit_sha: str) -> Dict[str, Optional[str]]:
        payload: Dict[str, Optional[str]] = {"stack_type": self.stack_type}
        stack_meta: Dict[str, object] = {}
        tags: List[str] = []
        edges: List[EdgePayload] = []

        meta = getattr(chunk, "meta", {}) or {}
        kind = meta.get("kind")

        if kind == "manifest":
            payload["component_type"] = "manifest"
            tags.append("manifest")
            if meta.get("components"):
                stack_meta["components"] = meta["components"]
        if kind == "layout":
            payload["component_type"] = payload.get("component_type") or "layout"
            layout_name = meta.get("layout_file") or os.path.splitext(os.path.basename(chunk.path))[0]
            payload["layout_file"] = layout_name
            payload["screen_name"] = payload.get("screen_name") or layout_name
            tags.append("layout")
            if meta.get("view_ids"):
                stack_meta["view_ids"] = meta["view_ids"]
            if meta.get("fragment_tags"):
                stack_meta["fragment_tags"] = meta["fragment_tags"]
            if meta.get("viewmodel_class"):
                stack_meta["viewmodel_class"] = meta["viewmodel_class"]
        if kind == "navgraph":
            payload["component_type"] = payload.get("component_type") or "navgraph"
            if meta.get("nav_graph_id"):
                payload["nav_graph_id"] = meta["nav_graph_id"]
                payload["screen_name"] = payload.get("screen_name") or meta["nav_graph_id"]
            tags.append("navgraph")
            if meta.get("destinations"):
                stack_meta["destinations"] = meta["destinations"]
            if meta.get("actions"):
                stack_meta["nav_actions"] = meta["actions"]
            if meta.get("start_destination"):
                stack_meta["start_destination"] = meta["start_destination"]

        # Basic heuristics by path/symbol for Kotlin/Java chunks.
        path = chunk.path
        if path.endswith("AndroidManifest.xml"):
            payload["component_type"] = payload.get("component_type") or "manifest"
            tags.append("manifest")
        if "/res/layout/" in path and "layout_file" not in payload:
            layout_name = os.path.splitext(os.path.basename(path))[0]
            payload["layout_file"] = layout_name
            payload["screen_name"] = payload.get("screen_name") or layout_name
            payload["component_type"] = payload.get("component_type") or "layout"
            tags.append("layout")
        if "/res/navigation/" in path and "nav_graph_id" not in payload:
            nav_id = os.path.splitext(os.path.basename(path))[0]
            payload["nav_graph_id"] = nav_id
            payload["screen_name"] = payload.get("screen_name") or nav_id
            payload["component_type"] = payload.get("component_type") or "navgraph"
            tags.append("navgraph")

        symbol = chunk.symbol.lower()
        if symbol.startswith("android:component:"):
            parts = symbol.split(":")
            if len(parts) >= 4:
                payload["component_type"] = payload.get("component_type") or parts[2]
                payload["screen_name"] = payload.get("screen_name") or parts[3]
                tags.append(parts[2])
        if symbol.startswith("class:"):
            class_name = symbol.split(":", 1)[1]
            if class_name.endswith("activity"):
                payload["component_type"] = payload.get("component_type") or "activity"
            if class_name.endswith("fragment"):
                payload["component_type"] = payload.get("component_type") or "fragment"
            payload["screen_name"] = payload.get("screen_name") or class_name

        # Heuristic edge extraction from code content for layouts/nav/actions/API calls.
        content = getattr(chunk, "content", "") or ""
        if content and (chunk.path.endswith(".kt") or chunk.path.endswith(".java") or kind in (None, "xml")):
            # Layout binding via R.layout.*
            for match in re.findall(r"R\.layout\.([A-Za-z0-9_]+)", content):
                target = normalize_layout_target(match)
                if target:
                    edges.append(build_edge(EdgeType.BINDS_LAYOUT, target))
            # NavController navigate calls
            for match in re.findall(r"navigate\(\s*R\.id\.([A-Za-z0-9_]+)", content):
                target = normalize_id(match)
                if target:
                    edges.append(build_edge(EdgeType.NAVIGATES_TO, target))
            # startActivity(Intent(..., SomeActivity::class.java))
            for match in re.findall(r"startActivity\([^)]*?([A-Za-z0-9_]+Activity)", content):
                target = normalize_id(match)
                if target:
                    edges.append(build_edge(EdgeType.NAVIGATES_TO, target))
            # Simple API call heuristic: serviceApi.method(…) or serviceService.method(…)
            for service, method in re.findall(r"([A-Za-z0-9_]+(?:Api|Service))\.([A-Za-z0-9_]+)\(", content):
                target = f"{service}.{method}"
                edges.append(build_edge(EdgeType.CALLS_API, target))

        if meta.get("summary"):
            payload["stack_text"] = meta["summary"]
        if meta.get("edges"):
            edges.extend(meta["edges"])
        if edges:
            payload["edges"] = dedupe_edges(edges)
        if stack_meta:
            payload["stack_meta"] = stack_meta
        if tags:
            payload["tags"] = sorted(set([t for t in tags if t]))

        # Normalize screen_name for predictable filtering (case-insensitive).
        if payload.get("screen_name"):
            payload["screen_name"] = str(payload["screen_name"]).lower()

        return {k: v for k, v in payload.items() if v is not None}
