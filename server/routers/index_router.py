from __future__ import annotations

import json
import logging
from typing import List

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from qdrant_client.models import PointStruct

from server.config import Config
from server.services.git_aware_code_indexer import Chunker, DiffUtil, GitCLI, Indexer
from server.services.initializers import Initializer
from server.services.repository_registry import Repository, RepositoryRegistry
from server.services.state_manager import (
    get_repo_path,
    list_git_repositories,
    load_state,
    save_state,
    sync_state_with_registry,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/repos", tags=["index"])


def _config(request: Request) -> Config:
    return request.app.state.config


def _registry(request: Request) -> RepositoryRegistry:
    return request.app.state.registry


def _initializer(request: Request) -> Initializer:
    return request.app.state.initializer


def _ensure_repo_registry_entry(request: Request, repo_id: str) -> Repository:
    config = _config(request)
    registry = _registry(request)
    defaults = {
        "name": repo_id,
        "collection_name": config.COLLECTION,
        "embedding_model": config.EMB_MODEL,
    }
    repo = registry.ensure_repository(repo_id, defaults)
    if repo.archived:
        raise HTTPException(status_code=400, detail=f"Repository '{repo_id}' is archived")
    return repo


@router.get("", response_model=List[str])
def list_repos(request: Request):
    return list_git_repositories(_config(request).REPOS_DIR)


@router.post("/{repo_id}/index/full")
def full_index(request: Request, repo_id: str):
    generator = _generate_full_index_progress(request, repo_id)
    return StreamingResponse(generator, media_type="application/json")


@router.post("/{repo_id}/index/update")
def update_index(request: Request, repo_id: str):
    generator = _generate_update_index_progress(request, repo_id)
    return StreamingResponse(generator, media_type="application/json")


def _generate_full_index_progress(request: Request, repo_id: str):
    config = _config(request)
    registry = _registry(request)
    initializer = _initializer(request)

    try:
        repo_entry = _ensure_repo_registry_entry(request, repo_id)
        sync_state_with_registry(config.STATE_FILE, repo_id, repo_entry.last_indexed_commit)
        repo_path = get_repo_path(config.REPOS_DIR, repo_id)
        emb_client, store_client = initializer.resolve_clients(repo_entry.collection_name, repo_entry.embedding_model)
        git = GitCLI(str(repo_path))
        head = git.get_head()
        indexer = Indexer(str(repo_path), repo_id, emb_client, store_client, repo_entry.collection_name)
        files = indexer.git.list_files(head)
        total_files = len(files)
        processed = 0

        yield json.dumps(
            {
                "status": "started",
                "message": "Starting full index",
                "total_files": total_files,
                "processed_files": 0,
                "last_commit": head,
            }
        ) + "\n"

        for path in files:
            head_src = indexer.git.show_file(head, path) or ""
            if head_src:
                file_chunks = Chunker.chunks(head_src, path, repo_id)
                if file_chunks:
                    texts = [c.content for c in file_chunks]
                    vectors = emb_client.embed(texts)
                    points = []
                    for c, v in zip(file_chunks, vectors):
                        payload = indexer._build_payload(c, config.BRANCH, head)
                        points.append(PointStruct(id=payload["point_id"], vector=v, payload=payload))
                    if points:
                        store_client.upsert_points(points)

                    processed += 1
                    yield json.dumps(
                        {
                            "status": "processing",
                            "message": f"Processed file: {path}",
                            "file": path,
                            "total_files": total_files,
                            "processed_files": processed,
                            "last_commit": head,
                        }
                    ) + "\n"
                else:
                    processed += 1
                    yield json.dumps(
                        {
                            "status": "processing",
                            "message": f"Skipped empty file: {path}",
                            "file": path,
                            "total_files": total_files,
                            "processed_files": processed,
                            "last_commit": head,
                        }
                    ) + "\n"
            else:
                processed += 1
                yield json.dumps(
                    {
                        "status": "processing",
                        "message": f"Skipped missing file: {path}",
                        "file": path,
                        "total_files": total_files,
                        "processed_files": processed,
                        "last_commit": head,
                    }
                ) + "\n"

        state = load_state(config.STATE_FILE)
        state[repo_id] = head
        save_state(config.STATE_FILE, state)
        registry.update_last_indexed_commit(repo_id, head)
        yield json.dumps(
            {
                "status": "completed",
                "message": "Full index completed",
                "total_files": total_files,
                "processed_files": processed,
                "last_commit": head,
            }
        ) + "\n"
        logger.info("Full index complete for %s", repo_id)
    except Exception as exc:
        yield json.dumps({"status": "error", "message": str(exc)}) + "\n"
        logger.exception("Full index error for %s", repo_id)


def _generate_update_index_progress(request: Request, repo_id: str):
    config = _config(request)
    registry = _registry(request)
    initializer = _initializer(request)

    try:
        repo_entry = _ensure_repo_registry_entry(request, repo_id)
        sync_state_with_registry(config.STATE_FILE, repo_id, repo_entry.last_indexed_commit)
        repo_path = get_repo_path(config.REPOS_DIR, repo_id)
        emb_client, store_client = initializer.resolve_clients(repo_entry.collection_name, repo_entry.embedding_model)
        git = GitCLI(str(repo_path))
        head = git.get_head()
        state = load_state(config.STATE_FILE)
        base = state.get(repo_id)

        logger.info("Update Index: repo=%s base=%s head=%s", repo_id, base, head)

        if not base:
            yield json.dumps(
                {"status": "error", "message": "No base commit found; run full index first.", "last_commit": head}
            ) + "\n"
            return

        indexer = Indexer(str(repo_path), repo_id, emb_client, store_client, repo_entry.collection_name)

        if base != head:
            diff_text = indexer.git.diff_unified_0(base, head)
            file_diffs = DiffUtil.parse_unified_diff(diff_text)
            if not file_diffs and diff_text.strip():
                logger.error("Diff parsing failed for repo %s", repo_id)
            if not file_diffs:
                yield json.dumps(
                    {"status": "noop", "message": "No changes detected between commits", "last_commit": head}
                ) + "\n"
                return
            total_files = len(file_diffs)
            processed = 0
            commit_sha = head
        else:
            status_out = indexer.git._run("status", "--porcelain", "--untracked-files=no") or ""
            status_letters = ("M", "A", "D", "R", "C", "U", "T")
            changed_paths = [
                line[3:].strip()
                for line in status_out.splitlines()
                if len(line) >= 3 and (line[0] in status_letters or line[1] in status_letters)
            ]
            if not changed_paths:
                yield json.dumps(
                    {"status": "noop", "message": "No local changes detected", "last_commit": head}
                ) + "\n"
                return
            diff_text = indexer.git.diff_to_working(base, changed_paths)
            file_diffs = DiffUtil.parse_unified_diff(diff_text)
            commit_sha = base
            total_files = len(file_diffs)
            processed = 0

        yield json.dumps(
            {
                "status": "started",
                "message": "Starting incremental index",
                "total_files": total_files,
                "processed_files": 0,
                "last_commit": head,
            }
        ) + "\n"

        for fd in file_diffs:
            if fd.is_deleted:
                base_src = indexer.git.show_file(base, fd.path) or ""
                if base_src:
                    try:
                        base_chunks = {c.symbol: c for c in Chunker.chunks(base_src, fd.path, repo_id)}
                        remove_ids = []
                        for _, ch in base_chunks.items():
                            olds = store_client.scroll_by_logical(ch.logical_id, is_latest=True)
                            remove_ids.extend([p.id for p in olds])
                        if remove_ids:
                            from qdrant_client.http.models import PointIdsList

                            store_client.client.delete(
                                collection_name=repo_entry.collection_name,
                                points_selector=PointIdsList(points=remove_ids),
                            )
                            logger.info("[DELETE] Removed %s vectors for %s", len(remove_ids), fd.path)
                    except Exception as exc:
                        logger.error("Failed to remove deleted file %s: %s", fd.path, exc)

                processed += 1
                yield json.dumps(
                    {
                        "status": "processing",
                        "message": f"Removed deleted file: {fd.path}",
                        "file": fd.path,
                        "total_files": total_files,
                        "processed_files": processed,
                        "last_commit": head,
                    }
                ) + "\n"
                continue

            head_src = indexer.git.show_file(head if base != head else None, fd.path) or ""
            if not head_src:
                processed += 1
                yield json.dumps(
                    {
                        "status": "processing",
                        "message": f"Skipped missing file: {fd.path}",
                        "file": fd.path,
                        "total_files": total_files,
                        "processed_files": processed,
                        "last_commit": head,
                    }
                ) + "\n"
                continue

            try:
                head_chunks = {c.symbol: c for c in Chunker.chunks(head_src, fd.path, repo_id)}
            except Exception as exc:
                processed += 1
                yield json.dumps(
                    {
                        "status": "error",
                        "message": f"Chunking failed for {fd.path}: {exc}",
                        "file": fd.path,
                        "total_files": total_files,
                        "processed_files": processed,
                        "last_commit": head,
                    }
                ) + "\n"
                continue

            to_embed = []
            to_update_only_pos = []

            for symbol, chunk in head_chunks.items():
                olds = store_client.scroll_by_logical(chunk.logical_id, is_latest=True)
                if not olds:
                    to_embed.append(chunk)
                    continue
                if base != head:
                    to_embed.append(chunk)
                    continue
                relocalized = DiffUtil.translate(chunk.range, fd.hunks)
                if relocalized.relocalize:
                    to_embed.append(chunk)
                else:
                    to_update_only_pos.append((chunk, relocalized))

            if to_embed:
                texts = [c.content for c in to_embed]
                vectors = emb_client.embed(texts)
                points = []
                for chunk, vector in zip(to_embed, vectors):
                    olds = store_client.scroll_by_logical(chunk.logical_id, is_latest=True)
                    if olds:
                        store_client.set_payload([p.id for p in olds], {"is_latest": False})
                    payload = indexer._build_payload(chunk, config.BRANCH, commit_sha)
                    points.append(PointStruct(id=payload["point_id"], vector=vector, payload=payload))
                if points:
                    store_client.upsert_points(points)

            if to_update_only_pos:
                for chunk, translated in to_update_only_pos:
                    olds = store_client.scroll_by_logical(chunk.logical_id, is_latest=True)
                    if olds:
                        store_client.set_payload([p.id for p in olds], {"lines": [translated.start_line, translated.end_line]})

            processed += 1
            yield json.dumps(
                {
                    "status": "processing",
                    "message": f"Processed file: {fd.path}",
                    "file": fd.path,
                    "total_files": total_files,
                    "processed_files": processed,
                    "last_commit": head,
                }
            ) + "\n"

        state[repo_id] = head
        save_state(config.STATE_FILE, state)
        registry.update_last_indexed_commit(repo_id, head)
        yield json.dumps(
            {
                "status": "completed",
                "message": "Incremental index completed",
                "total_files": total_files,
                "processed_files": processed,
                "last_commit": head,
            }
        ) + "\n"
    except Exception as exc:
        yield json.dumps(
            {"status": "error", "message": str(exc), "last_commit": locals().get("head")}
        ) + "\n"
        logger.exception("Update index error for %s", repo_id)
