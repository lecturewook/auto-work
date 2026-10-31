"""네트워크 리스너·웹서버·자동 업데이트 없는 로컬 화면 진입점."""
import sys
from pathlib import Path
from budget_offline.privileges import require_standard_user, PrivilegeError, show_error


def main():
    try:
        require_standard_user()
    except PrivilegeError as error:
        show_error(error)
        return 1
    if (Path(__file__).resolve().parent / 'PACKAGE_MANIFEST.json').exists():
        from tools.verify_bundle import main as verify_bundle
        if verify_bundle():
            return 1
    from budget_offline.gui import main as gui_main
    return gui_main()


if __name__=='__main__':
    sys.exit(main())
