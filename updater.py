# -*- coding: utf-8 -*-
"""GitHub Releases update checker for Course Manager.

This module only checks release metadata and opens the release page. It never
writes to the app database or installs an update automatically.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from urllib.parse import urlparse

APP_VERSION = "1.0.2"
GITHUB_OWNER = "WuXian-1023"
GITHUB_REPO = "course-manager"
RELEASES_API = (
    f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
)


def version_tuple(value: str) -> tuple[int, ...]:
    """Parse versions such as v1.2.3 or 1.2.3-beta into numeric tuples."""
    text = str(value or "").strip()
    text = text[1:] if text.lower().startswith("v") else text
    match = re.match(r"^(\d+(?:\.\d+)*)", text)
    if not match:
        raise ValueError(f"无法识别版本号：{value!r}")
    parts = [int(part) for part in match.group(1).split(".")]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def is_newer_version(latest: str, current: str = APP_VERSION) -> bool:
    return version_tuple(latest) > version_tuple(current)


def check_github_release(timeout: float = 8.0) -> dict:
    """Return latest published GitHub release metadata.

    A missing release (GitHub HTTP 404) is reported as a clear ValueError.
    Draft and prerelease releases are excluded by GitHub's /latest endpoint.
    """
    request = urllib.request.Request(
        RELEASES_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"CourseManager/{APP_VERSION}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read(512 * 1024)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise ValueError("GitHub 仓库目前还没有正式发布的 Release。") from exc
        raise RuntimeError(f"GitHub 更新服务返回 HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"连接 GitHub 失败：{exc}") from exc

    try:
        release = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("GitHub 返回的更新信息无法解析。") from exc

    if not isinstance(release, dict):
        raise ValueError("GitHub Release 数据格式不正确。")

    tag = str(release.get("tag_name") or "").strip()
    page_url = str(release.get("html_url") or "").strip()
    if not tag or not page_url:
        raise ValueError("Release 缺少版本号或发布页面地址。")
    parsed = urlparse(page_url)
    if parsed.scheme != "https" or parsed.netloc.lower() not in {
        "github.com", "www.github.com"
    }:
        raise ValueError("Release 页面地址不是可信的 GitHub HTTPS 地址。")

    # Validate the version before returning it to the UI.
    version_tuple(tag)
    return {
        "version": tag.lstrip("vV"),
        "tag_name": tag,
        "url": page_url,
        "notes": str(release.get("body") or "暂无更新说明").strip(),
        "published_at": str(release.get("published_at") or ""),
        "assets": release.get("assets") if isinstance(release.get("assets"), list) else [],
    }
