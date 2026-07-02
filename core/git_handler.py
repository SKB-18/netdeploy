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
        
        [CURSOR IMPLEMENTS clone-or-open logic using GitPython]
        """
        self.repo_path = repo_path
        self.remote_url = remote_url
        self.repo = None  # Cursor: set to git.Repo(...)

        # Cursor:
        # from git import Repo, InvalidGitRepositoryError
        # try:
        #     self.repo = Repo(repo_path)
        # except InvalidGitRepositoryError:
        #     os.makedirs(repo_path, exist_ok=True)
        #     if remote_url:
        #         self.repo = Repo.clone_from(remote_url, repo_path)
        #     else:
        #         self.repo = Repo.init(repo_path)

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

        # Cursor:
        # self.repo.index.add([config_path])
        # actor = git.Actor("NetDeploy", user_email)
        # commit = self.repo.index.commit(message, author=actor, committer=actor)
        # self.push()
        # return commit.hexsha

        logger.info("Config committed for device %s (placeholder)", device_id)
        return "0000000000000000000000000000000000000000"  # Cursor replaces

    def get_version(self, device_id: str, commit_hash: str) -> dict:
        """
        Fetch config dict from a specific Git commit.

        Returns deserialized YAML as dict.
        
        [CURSOR IMPLEMENTS]
        """
        # Cursor:
        # commit = self.repo.commit(commit_hash)
        # blob = commit.tree / "devices" / f"{device_id}.yaml"
        # return yaml.safe_load(blob.data_stream.read())
        logger.warning("get_version not implemented — returning empty dict")
        return {}

    def get_diff(self, device_id: str, v1: str, v2: str) -> str:
        """
        Return unified diff between two commit versions of a device config.

        v1, v2: commit hashes
        Returns unified diff string.
        
        [CURSOR IMPLEMENTS]
        """
        # Cursor:
        # c1 = self.repo.commit(v1)
        # c2 = self.repo.commit(v2)
        # diffs = c1.diff(c2, paths=[f"devices/{device_id}.yaml"], create_patch=True)
        # return "\n".join(d.diff.decode() for d in diffs)
        return "--- a/devices/{device_id}.yaml\n+++ b/devices/{device_id}.yaml\n[not implemented]"

    def list_versions(self, device_id: str, limit: int = 20) -> List[dict]:
        """
        Return commit history for a specific device.

        Returns list of dicts: [{commit, message, author, date}, ...]
        
        [CURSOR IMPLEMENTS]
        """
        # Cursor:
        # commits = list(self.repo.iter_commits(paths=f"devices/{device_id}.yaml", max_count=limit))
        # return [
        #     {
        #         "commit": c.hexsha,
        #         "message": c.message.strip(),
        #         "author": c.author.email,
        #         "date": c.authored_datetime.isoformat(),
        #     }
        #     for c in commits
        # ]
        return []

    def push(self):
        """Push commits to the configured remote origin."""
        if self.repo and self.remote_url:
            # Cursor: self.repo.remotes.origin.push()
            logger.info("Push to remote (placeholder)")
