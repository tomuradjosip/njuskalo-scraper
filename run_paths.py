"""Helpers for isolating scrape outputs per named run."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(BASE_DIR, "backend")
RUNS_DIR = os.path.join(BACKEND_DIR, "runs")


def sanitize_run_name(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", name.strip())
    cleaned = cleaned.strip("-._")
    if not cleaned:
        raise ValueError("Run name must contain at least one alphanumeric character")
    return cleaned[:80]


def resolve_paths(run_name: str | None = None) -> dict:
    """Return website/json/phone/log paths for a run, or legacy shared backend dirs."""
    if run_name:
        run = sanitize_run_name(run_name)
        root = os.path.join(RUNS_DIR, run)
        paths = {
            "run_name": run,
            "root": root,
            "website": os.path.join(root, "website"),
            "json": os.path.join(root, "json"),
            "phone_db_dir": os.path.join(root, "phoneDB"),
            "phone_db": os.path.join(root, "phoneDB", "phones.db"),
            "logs": os.path.join(root, "logs"),
            "meta": os.path.join(root, "meta.json"),
            "checkpoints": os.path.join(root, "checkpoints"),
            "leaf_urls": os.path.join(root, "leaf_urls"),
        }
    else:
        paths = {
            "run_name": None,
            "root": BACKEND_DIR,
            "website": os.path.join(BACKEND_DIR, "website"),
            "json": os.path.join(BACKEND_DIR, "json"),
            "phone_db_dir": os.path.join(BACKEND_DIR, "phoneDB"),
            "phone_db": os.path.join(BACKEND_DIR, "phoneDB", "phones.db"),
            "logs": os.path.join(BACKEND_DIR, "logs"),
            "meta": None,
            "checkpoints": os.path.join(BASE_DIR, "checkpoints"),
            "leaf_urls": os.path.join(BACKEND_DIR, "categories", "leaf_urls"),
        }

    for key in ("website", "json", "phone_db_dir", "logs", "checkpoints", "leaf_urls"):
        os.makedirs(paths[key], exist_ok=True)
    return paths


def write_run_meta(paths: dict, url: str | None = None, extra: dict | None = None) -> None:
    if not paths.get("meta"):
        return
    meta = {
        "run_name": paths["run_name"],
        "updated_at": datetime.now().isoformat(),
        "url": url,
        "paths": {
            "website": paths["website"],
            "json": paths["json"],
            "phone_db": paths["phone_db"],
            "logs": paths["logs"],
        },
    }
    if extra:
        meta.update(extra)
    if os.path.exists(paths["meta"]):
        try:
            with open(paths["meta"], "r", encoding="utf-8") as f:
                existing = json.load(f)
            if not url and existing.get("url"):
                meta["url"] = existing["url"]
            if existing.get("created_at"):
                meta["created_at"] = existing["created_at"]
        except Exception:
            pass
    meta.setdefault("created_at", meta["updated_at"])
    with open(paths["meta"], "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
