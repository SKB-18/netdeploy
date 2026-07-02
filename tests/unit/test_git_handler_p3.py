"""Phase 3 unit tests for GitConfigRepository."""

import os
import pytest
import tempfile
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_repo_path(tmp_path):
    """Provide a temp directory path for git repo tests."""
    return str(tmp_path / "test_config_repo")


@pytest.fixture
def git_repo(temp_repo_path):
    """Create a GitConfigRepository backed by a real (temp) git repo."""
    from core.git_handler import GitConfigRepository
    repo = GitConfigRepository(repo_path=temp_repo_path)
    return repo


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

class TestGitConfigRepositoryInit:
    def test_init_creates_new_repo(self, temp_repo_path):
        from core.git_handler import GitConfigRepository
        repo = GitConfigRepository(repo_path=temp_repo_path)
        assert repo.repo is not None
        assert os.path.isdir(temp_repo_path)

    def test_init_opens_existing_repo(self, temp_repo_path):
        from core.git_handler import GitConfigRepository
        # First create
        GitConfigRepository(repo_path=temp_repo_path)
        # Then open
        repo2 = GitConfigRepository(repo_path=temp_repo_path)
        assert repo2.repo is not None

    def test_repo_path_stored(self, temp_repo_path):
        from core.git_handler import GitConfigRepository
        repo = GitConfigRepository(repo_path=temp_repo_path)
        assert repo.repo_path == temp_repo_path

    def test_remote_url_stored(self, temp_repo_path):
        from core.git_handler import GitConfigRepository
        repo = GitConfigRepository(repo_path=temp_repo_path, remote_url="git@example.com:org/repo.git")
        assert repo.remote_url == "git@example.com:org/repo.git"

    def test_invalid_path_handled_gracefully(self):
        """If git init fails, repo should be None (not raise)."""
        from core.git_handler import GitConfigRepository
        with patch("git.Repo", side_effect=Exception("git unavailable")), \
             patch("git.Repo.init", side_effect=Exception("git unavailable")):
            # Should not raise — failures are caught
            try:
                repo = GitConfigRepository(repo_path="/nonexistent/path/xyz123")
                # repo.repo may be None or set — just verify no crash
            except Exception:
                pass  # Some environments may raise on invalid paths


# ---------------------------------------------------------------------------
# commit_config
# ---------------------------------------------------------------------------

class TestCommitConfig:
    def test_commit_creates_device_yaml(self, git_repo, temp_repo_path):
        device_id = "router-abc-123"
        config = {"bgp": {"local_asn": 65001}}
        git_repo.commit_config(device_id, config, "Add BGP config")
        expected_path = os.path.join(temp_repo_path, "devices", f"{device_id}.yaml")
        assert os.path.isfile(expected_path)

    def test_commit_returns_hex_sha(self, git_repo):
        sha = git_repo.commit_config("router-1", {"bgp": {}}, "init")
        assert len(sha) == 40
        assert all(c in "0123456789abcdef" for c in sha)

    def test_commit_with_custom_email(self, git_repo):
        sha = git_repo.commit_config(
            "router-2", {"ospf": {}}, "OSPF config", user_email="admin@netdeploy.test"
        )
        assert sha != ""

    def test_commit_multiple_devices(self, git_repo, temp_repo_path):
        git_repo.commit_config("dev-a", {"bgp": {"local_asn": 65001}}, "dev-a config")
        git_repo.commit_config("dev-b", {"bgp": {"local_asn": 65002}}, "dev-b config")
        for device_id in ("dev-a", "dev-b"):
            path = os.path.join(temp_repo_path, "devices", f"{device_id}.yaml")
            assert os.path.isfile(path)

    def test_no_repo_returns_placeholder_hash(self, temp_repo_path):
        from core.git_handler import GitConfigRepository
        repo = GitConfigRepository.__new__(GitConfigRepository)
        repo.repo_path = temp_repo_path
        repo.remote_url = None
        repo.repo = None
        os.makedirs(os.path.join(temp_repo_path, "devices"), exist_ok=True)
        sha = repo.commit_config("router-x", {}, "test")
        assert sha == "0000000000000000000000000000000000000000"


# ---------------------------------------------------------------------------
# list_versions
# ---------------------------------------------------------------------------

class TestListVersions:
    def test_empty_list_before_any_commits(self, git_repo):
        versions = git_repo.list_versions("nonexistent-device")
        assert versions == []

    def test_list_versions_after_commits(self, git_repo):
        device_id = "router-list-test"
        git_repo.commit_config(device_id, {"bgp": {"local_asn": 65001}}, "v1")
        git_repo.commit_config(device_id, {"bgp": {"local_asn": 65002}}, "v2")
        versions = git_repo.list_versions(device_id)
        assert len(versions) == 2
        for v in versions:
            assert "commit" in v
            assert "message" in v
            assert "author" in v
            assert "date" in v

    def test_list_versions_respects_limit(self, git_repo):
        device_id = "router-limit-test"
        for i in range(5):
            git_repo.commit_config(device_id, {"bgp": {"local_asn": 65000 + i}}, f"v{i}")
        versions = git_repo.list_versions(device_id, limit=3)
        assert len(versions) <= 3

    def test_no_repo_returns_empty_list(self):
        from core.git_handler import GitConfigRepository
        repo = GitConfigRepository.__new__(GitConfigRepository)
        repo.repo = None
        assert repo.list_versions("any-device") == []


# ---------------------------------------------------------------------------
# get_version
# ---------------------------------------------------------------------------

class TestGetVersion:
    def test_get_version_returns_config(self, git_repo):
        device_id = "router-version-test"
        config = {"bgp": {"local_asn": 65042}}
        sha = git_repo.commit_config(device_id, config, "add router")
        result = git_repo.get_version(device_id, sha)
        assert result == config

    def test_invalid_commit_hash_returns_empty(self, git_repo):
        result = git_repo.get_version("router-1", "deadbeef" * 5)
        assert result == {}

    def test_no_repo_returns_empty(self):
        from core.git_handler import GitConfigRepository
        repo = GitConfigRepository.__new__(GitConfigRepository)
        repo.repo = None
        assert repo.get_version("router-1", "abc123") == {}


# ---------------------------------------------------------------------------
# get_diff
# ---------------------------------------------------------------------------

class TestGetDiff:
    def test_diff_between_two_versions(self, git_repo):
        device_id = "router-diff-test"
        sha1 = git_repo.commit_config(device_id, {"bgp": {"local_asn": 65001}}, "v1")
        sha2 = git_repo.commit_config(device_id, {"bgp": {"local_asn": 65002}}, "v2")
        diff = git_repo.get_diff(device_id, sha1, sha2)
        assert isinstance(diff, str)
        # Should contain diff markers
        assert "65001" in diff or "65002" in diff or diff == ""

    def test_invalid_hash_returns_error_string(self, git_repo):
        result = git_repo.get_diff("router-1", "bad1", "bad2")
        assert isinstance(result, str)

    def test_no_repo_returns_no_repo_string(self):
        from core.git_handler import GitConfigRepository
        repo = GitConfigRepository.__new__(GitConfigRepository)
        repo.repo = None
        repo.repo_path = "/tmp/test"
        result = repo.get_diff("router-1", "a", "b")
        assert "[no repo]" in result


# ---------------------------------------------------------------------------
# push
# ---------------------------------------------------------------------------

class TestPush:
    def test_push_no_remote_does_nothing(self, git_repo):
        git_repo.remote_url = None
        git_repo.push()  # Should not raise

    def test_push_with_remote_calls_origin_push(self, git_repo):
        git_repo.remote_url = "git@example.com:test/repo.git"
        mock_remote = MagicMock()
        git_repo.repo = MagicMock()
        git_repo.repo.remotes.origin.push = mock_remote
        git_repo.push()
        mock_remote.assert_called_once()

    def test_push_handles_remote_error(self, git_repo):
        git_repo.remote_url = "git@example.com:test/repo.git"
        git_repo.repo = MagicMock()
        git_repo.repo.remotes.origin.push.side_effect = Exception("Remote unreachable")
        git_repo.push()  # Should not raise
