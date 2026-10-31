import io
import sys
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from budget_offline import privileges
from budget_offline.project import Project
import run_app


def windows_state(monkeypatch, *, elevated=False, failure=False):
    monkeypatch.setattr(privileges, 'is_windows', lambda: True)
    query = Mock(side_effect=OSError('token query failed')) if failure else Mock(return_value=elevated)
    monkeypatch.setattr(privileges, '_windows_token_elevated', query)
    return query


def test_normal_windows_token_allows_gui(monkeypatch):
    query = windows_state(monkeypatch)
    gui = Mock(return_value=0)
    monkeypatch.setitem(sys.modules, 'budget_offline.gui', SimpleNamespace(main=gui))
    assert run_app.main() == 0
    query.assert_called_once()
    gui.assert_called_once()


def test_project_keeps_user_selected_name(tmp_path):
    with Project(tmp_path/'project',create=True,name='2026 가상예산') as project:
        assert project.meta('name')=='2026 가상예산'


@pytest.mark.parametrize('failure',[False,True])
def test_admin_or_unknown_token_prevents_gui(monkeypatch,failure):
    windows_state(monkeypatch,elevated=True,failure=failure)
    gui = Mock()
    monkeypatch.setitem(sys.modules,'budget_offline.gui',SimpleNamespace(main=gui))
    message = Mock()
    monkeypatch.setattr(run_app,'show_error',message)
    assert run_app.main()==1
    gui.assert_not_called()
    message.assert_called_once()


@pytest.mark.parametrize('failure',[False,True])
def test_admin_or_unknown_token_prevents_project_creation(monkeypatch,tmp_path,failure):
    windows_state(monkeypatch,elevated=True,failure=failure)
    target=tmp_path/'must-not-create'
    with pytest.raises(privileges.PrivilegeError):Project(target,create=True)
    assert not target.exists()


def test_admin_prevents_opening_existing_project(monkeypatch,tmp_path):
    path=tmp_path/'existing'
    with Project(path,create=True):pass
    before=(path/'project.db').read_bytes()
    windows_state(monkeypatch,elevated=True)
    with pytest.raises(privileges.PrivilegeError):Project(path)
    assert before==(path/'project.db').read_bytes()


def test_admin_prevents_worker_reading_request(monkeypatch):
    from budget_offline import worker
    windows_state(monkeypatch,elevated=True)
    request=Mock()
    monkeypatch.setattr(sys,'stdin',request)
    with pytest.raises(privileges.PrivilegeError):worker.main()
    request.read.assert_not_called()


def test_admin_prevents_selftest_writes(monkeypatch,tmp_path):
    from tools.selftest import run
    windows_state(monkeypatch,elevated=True)
    target=tmp_path/'test-data'
    with pytest.raises(privileges.PrivilegeError):run(target)
    assert not target.exists()


def test_unknown_privileges_prevent_test_launcher(monkeypatch):
    from tools import launch_selftest,verify_bundle
    windows_state(monkeypatch,failure=True)
    verifier=Mock()
    monkeypatch.setattr(verify_bundle,'main',verifier)
    monkeypatch.setattr(launch_selftest,'show_error',Mock())
    assert launch_selftest.main()==1
    verifier.assert_not_called()


@pytest.mark.parametrize('elevated',[False,True])
def test_windows_token_api_reads_value_and_closes_handle(monkeypatch,elevated):
    import ctypes
    kernel=SimpleNamespace(GetCurrentProcess=Mock(return_value=-1),CloseHandle=Mock(return_value=True))
    def opened(process,access,token):
        assert access==0x0008
        token._obj.value=77
        return True
    def token_info(token,info_class,buffer,size,returned):
        assert info_class==20 and token.value==77
        buffer._obj.value=int(elevated)
        returned._obj.value=size
        return True
    security=SimpleNamespace(OpenProcessToken=Mock(side_effect=opened),GetTokenInformation=Mock(side_effect=token_info))
    monkeypatch.setattr(ctypes,'WinDLL',lambda name,**kw:kernel if name=='kernel32' else security,raising=False)
    assert privileges._windows_token_elevated() is elevated
    assert kernel.CloseHandle.call_args[0][0].value==77
