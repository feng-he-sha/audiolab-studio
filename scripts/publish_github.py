"""Create a GitHub repository, push main/tag, set metadata and create a release.

Authentication uses GH_TOKEN if present, otherwise the token already stored in
Git Credential Manager (``git credential-manager github login``). The token is
never printed or written to disk.

Usage:
    python scripts/publish_github.py --repo-name audiolab-studio --visibility public
    python scripts/publish_github.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.github.com"
DESCRIPTION = "Local audio workbench: vocal/BGM classification, timbre clustering, ffmpeg processing."
TOPICS = ["audio-processing", "source-separation", "vocal", "timbre", "fastapi", "react", "ffmpeg"]


def run(
    cmd: list[str],
    *,
    input_text: str | None = None,
    check: bool = False,
    timeout: float = 180.0,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            input=input_text,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            env=env,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(cmd, 124, "", f"timeout after {timeout}s: {exc}")
    if check and proc.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc


def credential() -> tuple[str, str, str]:
    """Return (owner_hint, token, source). Never prints the token."""
    if os.environ.get("GH_TOKEN"):
        return "", os.environ["GH_TOKEN"], "GH_TOKEN"

    proc = run(
        ["git", "credential", "fill"],
        input_text="protocol=https\nhost=github.com\n\n",
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "没有可用的 GitHub 凭据。请先运行 `git credential-manager github login`，"
            "或设置 GH_TOKEN（repo scope）后重试。"
        )
    fields: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            fields[key] = value
    token = fields.get("password", "")
    if not token:
        raise RuntimeError("GitHub 凭据缺少 token；请重新登录 Git Credential Manager。")
    return fields.get("username", ""), token, "Git Credential Manager"


def owner_from_gcm() -> str:
    proc = run(["git", "credential-manager", "github", "list"])
    if proc.returncode == 0:
        for line in proc.stdout.splitlines():
            line = line.strip()
            if line and " " not in line:
                return line
    return ""


class GitHub:
    def __init__(self, token: str) -> None:
        self.token = token
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "AudioLab-Studio-Publisher",
            }
        )

    def request(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        response = self.session.request(method, f"{API}{path}", json=body, timeout=40)
        if response.status_code == 404:
            return 404, None
        if response.status_code >= 400:
            detail = ""
            try:
                detail = response.json().get("message", "")
            except Exception:
                pass
            raise RuntimeError(f"GitHub API {method} {path} -> HTTP {response.status_code}: {detail}")
        if not response.content:
            return response.status_code, None
        return response.status_code, response.json()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", default="")
    parser.add_argument("--repo-name", default="audiolab-studio")
    parser.add_argument("--visibility", choices=["public", "private"], default="public")
    parser.add_argument("--description", default=DESCRIPTION)
    parser.add_argument("--skip-release", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not (ROOT / ".git").exists():
        print(f"不是 git 仓库: {ROOT}")
        return 1
    dirty = run(["git", "status", "--porcelain"]).stdout.strip()
    if dirty:
        print("工作区有未提交修改，请先 git add/commit：")
        print(dirty)
        return 1

    tags = run(["git", "tag"]).stdout.split()
    if "v0.1.0" not in tags:
        if args.dry_run:
            print("[dry-run] 将创建 tag v0.1.0")
        else:
            run(["git", "tag", "-a", "v0.1.0", "-m", "AudioLab Studio v0.1.0"], check=True)

    if args.dry_run:
        owner = args.owner or owner_from_gcm() or "<GitHub账号>"
        print(f"[dry-run] 目标仓库: https://github.com/{owner}/{args.repo_name}")
        print(f"[dry-run] 可见性: {args.visibility}")
        print("[dry-run] 将创建仓库（若不存在）")
        print(f"[dry-run] git remote add/set-url origin https://github.com/{owner}/{args.repo_name}.git")
        print("[dry-run] git push -u origin main")
        print("[dry-run] git push origin v0.1.0")
        if not args.skip_release:
            print("[dry-run] 创建 Release v0.1.0")
        print("[dry-run] dry-run 结束，未修改远程")
        return 0

    owner_hint, token, source = credential()
    print(f"凭据来源: {source}")
    api = GitHub(token)
    _, me = api.request("GET", "/user")
    login = me["login"]
    owner = args.owner or login
    print(f"GitHub 账号: {login} / 目标: {owner}/{args.repo_name}")

    status, repo = api.request("GET", f"/repos/{owner}/{args.repo_name}")
    if status == 404:
        print("仓库不存在，创建中...")
        body = {
            "name": args.repo_name,
            "private": args.visibility == "private",
            "description": args.description,
            "auto_init": False,
        }
        if owner == login:
            _, repo = api.request("POST", "/user/repos", body)
        else:
            _, repo = api.request("POST", f"/orgs/{owner}/repos", body)
        print(f"已创建: {repo['html_url']}")
    else:
        print(f"仓库已存在: {repo['html_url']}")

    remote_url = f"https://github.com/{owner}/{args.repo_name}.git"
    existing = run(["git", "remote", "get-url", "origin"])
    if existing.returncode == 0:
        if existing.stdout.strip() != remote_url:
            run(["git", "remote", "set-url", "origin", remote_url], check=True)
    else:
        run(["git", "remote", "add", "origin", remote_url], check=True)

    print("推送 main...")
    push = run(["git", "push", "-u", "origin", "main"], timeout=300)
    if push.returncode != 0:
        print(push.stderr.strip() or push.stdout.strip())
        print("push 失败。请检查 Git Credential Manager 登录/权限，或手动 push。")
        return 1

    head_sha = run(["git", "rev-parse", "HEAD"]).stdout.strip()
    print("推送 tag v0.1.0...")
    push_tag = run(["git", "push", "origin", "v0.1.0"], timeout=90)
    if push_tag.returncode != 0:
        # Some Windows/GCM setups hang on annotated tag push even after main
        # succeeds; create the tag ref through the API instead.
        print("tag push 未完成，尝试通过 API 创建 tag ref...")
        try:
            api.request("POST", f"/repos/{owner}/{args.repo_name}/git/refs", {"ref": "refs/tags/v0.1.0", "sha": head_sha})
            print("已通过 API 创建 tag v0.1.0")
        except Exception as exc:
            print(f"tag 创建失败，可稍后手动 push: {exc}")

    try:
        api.request("PATCH", f"/repos/{owner}/{args.repo_name}", {"description": args.description})
        api.request("PUT", f"/repos/{owner}/{args.repo_name}/topics", {"names": TOPICS})
    except Exception as exc:
        print(f"描述/topics 更新失败（可忽略）: {exc}")

    if not args.skip_release:
        notes_path = ROOT / "docs" / "RELEASE_NOTES.md"
        notes = notes_path.read_text(encoding="utf-8") if notes_path.exists() else "AudioLab Studio v0.1.0"
        try:
            _, release = api.request(
                "POST",
                f"/repos/{owner}/{args.repo_name}/releases",
                {
                    "tag_name": "v0.1.0",
                    "name": "AudioLab Studio v0.1.0",
                    "body": notes,
                    "draft": False,
                    "prerelease": False,
                },
            )
            print(f"Release: {release['html_url']}")
        except Exception as exc:
            print(f"Release 创建失败（可手动创建）: {exc}")

    print(f"完成: https://github.com/{owner}/{args.repo_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
