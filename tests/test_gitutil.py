import subprocess

from friday import gitutil
from friday.orchestrator import Orchestrator
from tests.test_orchestrator import ScriptedAgents, make_root


def _log(ws):
    return subprocess.run(["git", "-C", str(ws), "log", "--format=%s"],
                          capture_output=True, text=True).stdout.splitlines()


def test_init_repo_creates_baseline(tmp_path):
    ws = tmp_path / "workspace"
    assert gitutil.init_repo(ws)
    assert gitutil.is_repo(ws)
    assert _log(ws) == ["friday: round 0 (workspace initialized)"]


def test_init_repo_idempotent(tmp_path):
    ws = tmp_path / "workspace"
    gitutil.init_repo(ws)
    (ws / "keep.txt").write_text("x")
    gitutil.commit_round(ws, 1)
    gitutil.init_repo(ws)  # must not re-init or wipe history
    assert _log(ws) == ["friday: round 1", "friday: round 0 (workspace initialized)"]


def test_is_repo_false_for_plain_dir(tmp_path):
    (tmp_path / "workspace").mkdir()
    assert not gitutil.is_repo(tmp_path / "workspace")


def test_commit_round_noop_without_repo(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    assert gitutil.commit_round(ws, 1) is False


def test_orchestrator_commits_each_round_in_git_workspace(tmp_path):
    root = make_root(tmp_path)
    gitutil.init_repo(root / "workspace")
    orch = Orchestrator(root=root, agents=ScriptedAgents([("stuck", False, True)] * 3))
    orch.run_round(1)
    orch.run_round(2)
    msgs = _log(root / "workspace")
    assert msgs[:3] == ["friday: round 2", "friday: round 1",
                        "friday: round 0 (workspace initialized)"]
