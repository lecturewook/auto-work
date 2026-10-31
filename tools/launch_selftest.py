"""일반 사용자 권한을 확인한 뒤 동봉 파일 확인·가상시험 실행."""
import sys
from datetime import datetime
from pathlib import Path
import os
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from budget_offline.privileges import require_standard_user, PrivilegeError, show_error


def main():
    try:
        require_standard_user()
    except PrivilegeError as error:
        show_error(error)
        return 1
    from tools.verify_bundle import main as verify_bundle
    if verify_bundle():
        return 1
    from tools.selftest import run
    base = Path(os.environ['LOCALAPPDATA']) if os.name == 'nt' else Path.home() / '.local/share'
    destination = base / 'BudgetOffline' / 'selftest-results' / (datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8])
    try:
        result = run(destination, 3)
        print(f'PASS: {len(result["tests"])} checks. Result: {destination / "result.json"}')
        return 0
    except Exception as error:
        print(f'FAILED: {type(error).__name__}: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
