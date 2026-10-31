"""Windows 업무 처리는 상승되지 않은 사용자 토큰으로만 허용한다."""
import sys


class PrivilegeError(RuntimeError):
    pass


def is_windows():
    return sys.platform == 'win32'


def _windows_token_elevated():
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    security = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    security.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    security.OpenProcessToken.restype = wintypes.BOOL
    security.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    security.GetTokenInformation.restype = wintypes.BOOL
    token = wintypes.HANDLE()
    if not security.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        elevated = wintypes.DWORD()
        returned = wintypes.DWORD()
        if not security.GetTokenInformation(token, 20, ctypes.byref(elevated), ctypes.sizeof(elevated), ctypes.byref(returned)):
            raise ctypes.WinError(ctypes.get_last_error())
        if returned.value != ctypes.sizeof(elevated) or elevated.value not in (0, 1):
            raise OSError('Unexpected Windows token information')
        return bool(elevated.value)
    finally:
        kernel.CloseHandle(token)


def require_standard_user():
    if not is_windows():
        return  # Linux 개발 시험. Windows 토큰 검증 성공을 뜻하지 않는다.
    try:
        elevated = _windows_token_elevated()
    except Exception as exc:
        raise PrivilegeError('실행 권한을 확인할 수 없어 중단했습니다. 관리자 권한으로 다시 실행하지 말고 기관 담당자에게 확인하세요.') from exc
    if elevated:
        raise PrivilegeError('관리자 권한 실행을 차단했습니다. 이 창을 닫고 일반 사용자로 실행.cmd를 더블클릭하세요. 바로가기의 “관리자 권한으로 실행” 설정도 해제하세요.')


def show_error(error):
    print(str(error), file=sys.stderr)
    if is_windows():
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, str(error), '일반 사용자 실행만 허용', 0x10)
