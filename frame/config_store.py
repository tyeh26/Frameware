"""Atomic, comment-preserving updates to config.yaml (ruamel.yaml)."""

from __future__ import annotations

import os
import tempfile

from ruamel.yaml import YAML


def _load_cfg(path: str, ryaml: YAML) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        cfg = ryaml.load(f)
    if cfg is None:
        return {}
    if not isinstance(cfg, dict):
        raise ValueError("Config must be a YAML mapping.")
    return cfg


def _write_cfg(cfg: dict, path: str, dir_: str, ryaml: YAML) -> None:
    with tempfile.NamedTemporaryFile(
        "w", dir=dir_, delete=False, suffix=".tmp", encoding="utf-8"
    ) as tmp:
        tmp_path = tmp.name
        ryaml.dump(cfg, tmp)
    os.replace(tmp_path, path)


def update_tv_ip(config_path: str, ip: str) -> None:
    """Set tv.ip in YAML; preserves quotes/comments where ruamel allows."""
    path = os.path.abspath(config_path)
    ryaml = YAML()
    ryaml.preserve_quotes = True
    cfg = _load_cfg(path, ryaml)
    tv = cfg.get("tv")
    if not isinstance(tv, dict):
        cfg["tv"] = {}
        tv = cfg["tv"]
    tv["ip"] = ip
    _write_cfg(cfg, path, os.path.dirname(path), ryaml)


def update_base_image(config_path: str, rel_path: str) -> None:
    """Set art.base_image in YAML; preserves quotes/comments where ruamel allows."""
    path = os.path.abspath(config_path)
    ryaml = YAML()
    ryaml.preserve_quotes = True
    cfg = _load_cfg(path, ryaml)
    art = cfg.get("art")
    if not isinstance(art, dict):
        cfg["art"] = {}
        art = cfg["art"]
    art["base_image"] = rel_path
    _write_cfg(cfg, path, os.path.dirname(path), ryaml)
