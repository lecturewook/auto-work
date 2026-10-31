"""네트워크 리스너·웹서버·자동 업데이트 없는 로컬 화면 진입점."""
import os
import sys


def main():
    if os.name == 'nt':
        import ctypes
        if not ctypes.windll.shell32.IsUserAnAdmin():
            ctypes.windll.user32.MessageBoxW(None,'기관 승인 후 실행.cmd를 마우스 오른쪽 버튼으로 눌러 관리자 권한으로 실행하세요. 관리자 권한 자체가 보안을 보장하지는 않습니다.','실행 권한 확인',0x10)
            return 1
    from budget_offline.gui import main as gui_main
    return gui_main()


if __name__=='__main__':
    sys.exit(main())
