# 예산 근거 대조 — 내 PC 전용 로컬 웹 시험판 0.1.4

Windows 11 64비트 PC에서 Edge로 여는 예산자료 대조 시험판입니다. 문서·DB·검토·엑셀 출력·백업은 PC 안에서 처리합니다. 외부 API·AI·로그인·온라인 라이브러리를 사용하지 않습니다. Python이 포함된 Windows 묶음을 제공합니다.

**실제 양식의 자동 연결과 작성취합.xlsx 총괄DB 기입은 아직 미구현입니다.** 공식 최종본 출력은 잠겨 있습니다. 가상 3부서 자료로 원본 보존·연결 확인·단위 대조·승인·long/wide 출력·백업복구를 먼저 시험합니다.

## 받을 파일과 실행

- BudgetOffline-0.1.4-Windows-x64.zip: 권장 폴더형 실행 묶음. 모두 압축 풀기 → 실행.cmd 더블클릭 → Edge 열기. Python 설치 불필요.
- BudgetOffline-0.1.4-Windows-x64.exe: 같은 웹을 여는 단일 EXE. 기관의 실행 허가가 필요합니다. 코드서명하지 않았으므로 SmartScreen 경고가 나타날 수 있습니다.
- BudgetOffline-0.1.4-guides.zip: Markdown 안내서와 시연 이미지.
- BudgetOffline-0.1.4-source.zip: 수정 가능한 소스·가상자료·테스트·빌드 도구.

기관 반입 승인 후 [상세한 클릭 순서](docs/LOCAL_WEB_GUIDE.md)를 따르세요. 기본 주소는 실행 때 생성되는 `http://127.0.0.1:빈포트/#접속키`입니다. `192.168.180.198`을 비롯한 내부망 IP에서는 접속을 받지 않습니다. 실행 시 보여준 전체 주소를 Edge에서 사용하세요.

처음에는 **가상자료로 시작 → 원문 근거와 연결 → 상세 확인 → 연결 확인하여 저장 → 대조와 승인 → 상세 확인 → 승인 → 검토용 초안 엑셀** 순서입니다. 짝이 되는 양쪽 근거를 각각 확인해야 합니다. 종료는 **저장하고 프로그램 종료** 버튼을 누릅니다.

## 검증과 제한

Linux에서 실제 HTTP 요청과 Chromium으로 파일 6개·근거 24개·연결·초안 출력을 시험했습니다. HTTP 전체 흐름에서는 승인·엑셀·중복 차단·백업복구·재열기를 검증했습니다. **Windows 11·Edge 실행, 권한 전환, Windows 방화벽·기관 보안제품은 실기기 미검증**입니다. 웹 화면으로 바꿔도 처리 프로그램의 실행 허가가 필요합니다. PC 전체 보안을 보증하지 않습니다.

[사용법](docs/USER_GUIDE.md) · [백업·업데이트](docs/UPDATE_GUIDE.md) · [값과 연결 규칙](docs/DATA_RULES.md) · [보안](docs/SECURITY.md) · [시험 결과](docs/TEST_REPORT.md) · [문제 해결](docs/TROUBLESHOOTING.md) · [변경 기록](docs/CHANGELOG.md) · [빌드](docs/BUILD.md)

## 개발 환경에서 실행

의존성 준비는 제작 PC에서만 합니다. 업무 PC에서 인터넷으로 설치하는 절차가 아닙니다.

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python run_web.py --no-browser
```

표시된 LOCAL_WEB_READY 뒤 주소 전체를 이 PC의 브라우저에 입력합니다. 시험은 `.venv/bin/python -m pytest -q`, `.venv/bin/python tools/check_local_web.py`로 실행합니다. 네트워크 수신 자체를 금지한 개발 샌드박스에서는 루프백 시험 권한이 별도로 필요합니다. 기존 Qt 화면은 `run_app.py`에 보존했습니다.
