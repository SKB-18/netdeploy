"""
GitConfigRepository — version-controlled network configuration store.

Cowork provides: class interface, method stubs.
Cursor implements: commit_config, get_version, get_diff, list_versions, push.
"""

import logging
import os
from typing import Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)


class GitConfigRepository:
    """Manage network device configurations in a Git repository."""

    def __init__(self, repo_path: str, remote_url: Optional[str] = None):
        """
        Initialize or open a Git repository.

        If repo_path doesn't exist and remote_url is given, clone it.
        Otherwise open the existing repo at repo_path.
        """
        self.repo_path = repo_path
        self.remote_url = remote_url
        self.repo = None

        try:
            import git as gitlib
            try:
                self.repo = gitlib.Repo(repo_path)
                logger.info("Opened existing git repo at %s", repo_path)
            except (gitlib.InvalidGitRepositoryError, gitlib.NoSuchPathError, Exception):
                os.makedirs(repo_path, exist_ok=True)
                if remote_url:
                    self.repo = gitlib.Repo.clone_from(remote_url, repo_path)
                    logger.info("Cloned repo from %s to %s", remote_url, repo_path)
                else:
                    self.repo = gitlib.Repo.init(repo_path)
                    logger.info("Initialized new git repo at %s", repo_path)
        except Exception as e:
            logger.error("Failed to initialize git repo at %s: %s", repo_path, e)

    def commit_config(
        self,
        device_id: str,
        config_data: dict,
        message: str,
        user_email: str = "netdeploy@system",
    ) -> str:
        """
        Write config to devices/{device_id}.yaml, stage, commit, push.

        Returns the commit hash (40-char hex string).
        
        [CURSOR IMPLEMENTS]
        """
        device_dir = os.path.join(self.repo_path, "devices")
        os.makedirs(device_dir, exist_ok=True)
        config_path = os.path.join(device_dir, f"{device_id}.yaml")

        with open(config_path, "w") as f:
            yaml.dump(config_data, f, default_flow_style=False)

        if self.repo is None:
            logger.warning("No git repo — returning placeholder hash")
            return "0000000000000000000000000000000000000000"

        try:
            import git as gitlib
            self.repo.index.add([config_path])
            actor = gitlib.Actor("NetDeploy", user_email)
            commit = self.repo.index.commit(
                message,
                author=actor,
                committer=actor,
            )
            self.push()
            logger.info("Config committed for device %s: %s", device_id, commit.hexsha[:8])
            return commit.hexsha
        except Exception as e:
            logger.error("Git commit failed for device %s: %s", device_id, e)
            return "0000000000000000000000000000000000000000"

    def get_version(self, device_id: str, commit_hash: str) -> dict:
        """
        Fetch config dict from a specific Git commit.

        Returns deserialized YAML as dict.
        
        [CURSOR IMPLEMENTS]
        """
        if self.repo is None:
            return {}
        try:
            commit = self.repo.commit(commit_hash)
            blob = commit.tree / "devices" / f"{device_id}.yaml"
            return yaml.safe_load(blob.data_stream.read()) or {}
        except Exception as e:
            logger.error("get_version failed for device %s at %s: %s", device_id, commit_hash, e)
            return {}

    def get_diff(self, device_id: str, v1: str, v2: str) -> str:
        """
        Return unified diff between two commit versions of a device config.

        v1, v2: commit hashes
        Returns unified diff string.
        
        [CURSOR IMPLEMENTS]
        """
        if self.repo is None:
            return f"--- a/devices/{device_id}.yaml\n+++ b/devices/{device_id}.yaml\n[no repo]"
        try:
            c1 = self.repo.commit(v1)
            c2 = self.repo.commit(v2)
            diffs = c1.diff(c2, paths=[f"devices/{device_id}.yaml"], create_patch=True)
            return "\n".join(d.diff.decode() for d in diffs)
        except Exception as e:
            logger.error("get_diff failed for device %s: %s", device_id, e)
            return f"[diff error: {e}]"

    def list_versions(self, device_id: str, limit: int = 20) -> List[dict]:
        """
        Return commit history for a specific device.

        Returns list of dicts: [{commit, message, author, date}, ...]
        
        [CURSOR IMPLEMENTS]
        """
        if self.repo is None:
            return []
        try:
            commits = list(
                self.repo.iter_commits(paths=f"devices/{device_id}.yaml", max_count=limit)
            )
            return [
                {
                    "commit": c.hexsha,
                    "message": c.message.strip(),
                    "author": c.author.email,
                    "date": c.authored_datetime.isoformat(),
                }
                for c in commits
            ]
        except Exception as e:
            logger.error("list_versions failed for device %s: %s", device_id, e)
            return []

    def push(self):
        """Push commits to the configured remote origin."""
        if self.repo and self.remote_url:
            try:
                self.repo.remotes.origin.push()
                logger.info("Pushed to remote origin")
            except Exception as e:
                logger.warning("Push to remote failed: %s", e)
