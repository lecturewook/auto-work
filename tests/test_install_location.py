from unittest.mock import Mock

import pytest

from budget_offline import project as module
from budget_offline.backup import backup, restore
from budget_offline.project import Project
from budget_offline.safety import SafeError


@pytest.fixture
def installation(tmp_path, monkeypatch):
    root = tmp_path/'설치 캐시'
    root.mkdir()
    (root/'PACKAGE_MANIFEST.json').write_text('{}', encoding='utf-8')
    monkeypatch.setattr(module, 'APP_ROOT', root)
    return root


def test_project_cannot_pollute_bundled_runtime(installation):
    target = installation/'내 작업'
    with pytest.raises(SafeError, match='별도 로컬 작업'):
        Project(target, create=True)
    assert not target.exists()


def test_separate_project_allowed(installation, tmp_path):
    with Project(tmp_path/'가상 작업', create=True) as project:
        assert project.meta('schema') == '1'


def test_restore_blocked_before_reading_or_writing(installation):
    target = installation/'복구 작업'
    with pytest.raises(SafeError, match='별도 로컬 작업'):
        restore('missing-backup.zip', target)
    assert not target.exists()


def test_backup_blocked_before_reading_project(installation):
    project = Mock()
    with pytest.raises(SafeError, match='별도 로컬 작업'):
        backup(project, installation/'backup.zip')
    project.integrity.assert_not_called()
