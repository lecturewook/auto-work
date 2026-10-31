"""시간 제한이 걸리는 별도 프로세스. 출력은 작업 프로젝트 밖으로 전송되지 않는다."""
import json
import sys
from .readers import read_file
from .privileges import require_standard_user


def main():
    require_standard_user()
    request = json.loads(sys.stdin.read())
    try:
        result = read_file(request['path'], request['rules'])
    except Exception as e:
        from .safety import SafeError
        reason = str(e) if isinstance(e, SafeError) else f'파일 읽기 오류 ({type(e).__name__}). 손상·암호·구조를 확인하세요.'
        result = dict(status='처리 실패', reason=reason, observations=[])
    sys.stdout.write(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    main()
