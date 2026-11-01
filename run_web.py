"""내 PC 전용 웹 진입점. 높은 권한·배포 변조 확인 후에만 로컬 리스너 시작."""
import sys
from pathlib import Path
from budget_offline.privileges import require_standard_user, PrivilegeError, show_error


def main():
    try:
        require_standard_user()
        if (Path(__file__).resolve().parent/'PACKAGE_MANIFEST.json').exists():
            from tools.verify_bundle import main as verify
            if verify(): return 1
        from budget_offline.local_web import main as web
        return web(open_browser='--no-browser' not in sys.argv)
    except (PrivilegeError, OSError) as error:
        show_error(error)
        return 1


if __name__ == '__main__':
    sys.exit(main())
