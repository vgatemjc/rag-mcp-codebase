from tests.rag_test_utils import GitRepo, consume_streaming_json


def test_temp_env_sets_isolated_paths(temp_env):
    env = temp_env
    assert env.repos_dir.exists()
    assert env.registry_dir.exists()
    assert env.state_file.name == "index_state.json"


def test_git_repo_helper_can_commit(git_repo: GitRepo):
    repo = git_repo
    repo.write("file_a.py", "def foo():\n    return 'bar'\n")
    sha = repo.commit_all("add file_a")
    assert len(sha) == 40
    assert (repo.path / ".git").is_dir()


def test_consume_streaming_json_reads_last_line():
    class _DummyResponse:
        def iter_lines(self):
            yield b'{"status":"started"}'
            yield b'{"status":"processing"}'
            yield b'{"status":"completed","last_commit":"abc"}'

    result = consume_streaming_json(_DummyResponse())
    assert result["status"] == "completed"
    assert result["last_commit"] == "abc"
