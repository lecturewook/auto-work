# 개발과 재현 가능한 빌드

> 0.1.3 실행 방식: 단일 EXE를 그냥 더블클릭합니다. Windows에 일반 실행(asInvoker)을 명시했습니다. 높은 권한을 물려받으면 Windows의 UAC 연결 토큰, 같은 사용자 바탕화면 토큰, Windows 기본 사용자 제한 토큰 순서로 전환을 시도합니다. 전환 후보와 실제 자식 프로세스의 사용자·로그인 세션·상승 여부·무결성 수준·관리자 그룹·UI 접근 권한을 확인하고, 일반 권한인 경우에만 자료를 처리합니다. 전환 실패는 오류 코드를 표시하고 중단합니다. 아래의 단순 관리자 차단 설명은 이전 동작이며, ZIP의 실행.cmd에는 자동 전환 기능이 없습니다. Windows 보안 정책을 끄거나 변경하지 않습니다. Windows 11 실기기에서 자동 전환 성공 여부는 아직 미검증입니다.

업무 PC에서 인터넷에 접속해 설치하는 절차가 아닙니다. 아래는 가상자료만 사용하는 개발·묶음 제작용 절차입니다. Windows ZIP은 공식 Windows 바이너리를 모아서 만들고 EXE는 그 ZIP을 포함한 Go 시작 도구를 교차 컴파일합니다. 교차 컴파일은 Linux에서 Windows용 실행 파일을 만드는 것입니다. Linux에서 Windows 프로그램을 실행했다고 주장하지 않습니다.

## 소스 구성

- `budget_offline/readers.py`: HWPX/XLSX/HWP 텍스트 읽기. `worker.py`는 시간 제한용 별도 프로세스.
- `numbers.py`: 키·숫자·단위 변환. `project.py`: 원본 관리, DB, 연결·비교·승인.
- `outputs.py`: long/wide·근거 보고서·출력 검증. `backup.py`: 백업·복구.
- `gui.py`: 한국어 화면. `offline.py`: Python 소켓 금지. `privileges.py`: Windows 상승 권한 차단. `run_app.py`: 일반 사용자 확인·묶음 검증·화면 시작.
- `rules/demo-v1.json`: 새 프로젝트용 가상 규칙. `samples`: 처음부터 만든 가상 입력과 정답.
- `tests/test_workflow.py`: 기능·안전장치 시험. `tools/selftest.py`: pytest 없이 실행할 수 있는 전체 흐름 시험.
- `tools/check_gui.py`: Linux offscreen 화면·배치 취소 시험.
- `launcher/engine.go`: 내장 ZIP 검사·원자적 준비·캐시 무결성 확인. `main_windows.go`: Windows 토큰 검사·네이티브 준비창·동봉 Python 절대 경로 실행. 네트워크 패키지 사용 없음.
- `tools/prepare_go.py`, `build_standalone.py`: 제작 PC의 SDK 준비와 Windows 단일 EXE 빌드. 업무 실행에서는 호출하지 않음.
- `tools/windows_policy.ps1`: 기관 관리자만 사용하는 Windows 방화벽 설정/확인/제거. 업무 프로그램 실행과 분리. Windows 실기기 미검증.

## 개발 환경

Linux에서 Python 3.12와 그래픽 실행에 필요한 OS 라이브러리를 준비합니다. 저장소 최상위에서 아래 명령을 실행합니다.

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q --junitxml=test-result.xml
QT_QPA_PLATFORM=offscreen .venv/bin/python tools/check_gui.py
.venv/bin/python tools/selftest.py test-project-new --departments 52
```

가상자료를 다시 만들려면 `tools/make_fixtures.py 새폴더 --departments 3`을 실행합니다. 한컴으로 렌더링된 문서를 가장하는 기능은 없습니다. HWP 샘플은 OLE 구조와 HWP 레코드를 만든 구조 시험 파일입니다.

## Windows 오프라인 묶음 만들기

제작 PC 기준은 Linux x86-64, Python 3.12, Go 1.27.3입니다. 업무 PC에는 이 개발 도구들을 설치하지 않습니다. 저장소 최상위에서 실행합니다.

```sh
python tools/fetch_build_inputs.py
python tools/prepare_go.py
python tools/build_release.py
python tools/build_standalone.py
```

1. 첫 명령은 공식 NuGet/PyPI에서 `DEPENDENCY_HASHES.json`의 정확한 파일을 받아 해시를 검사합니다.
2. 두 번째는 `BUILD_TOOLCHAIN.json`에 기록된 공식 Go SDK를 받아 SHA-256 대조 후 `.build-tools/go`에 준비합니다. 이미 보관한 파일이 맞으면 네트워크를 사용하지 않습니다. 다른 `/usr/bin/go` 명령을 SDK로 가정하지 않습니다.
3. 세 번째는 네트워크 없이 Windows ZIP·소스 ZIP·안내서 ZIP을 만듭니다. `launcher/payload.zip`과 빌드 캐시는 소스 묶음에 포함하지 않습니다.
4. 네 번째는 실제 Windows ZIP을 넣어 Linux에서 경로·해시·누락·취소 시험을 실행한 뒤 `GOOS=windows GOARCH=amd64 CGO_ENABLED=0`으로 EXE를 만듭니다. Go 외부 모듈은 없고, 모듈 다운로드와 자동 도구 갱신을 막습니다. TLS·배포 파일 해시 검증을 끄지 않습니다.
5. `dist`의 `BudgetOffline-0.1.3-Windows-x64.exe`, 세 종류 ZIP, `SHA256SUMS.txt`, `STANDALONE_BUILD.json`을 확인합니다. EXE의 PE x64·GUI 형식과 정확한 ZIP 포함 여부를 검사합니다. 이것은 Windows 실행 시험을 대신하지 않습니다.
6. 기관의 Windows 11 64비트 시험 PC에서 `LOCAL_ACCEPTANCE.md`를 수행합니다. Python 미설치 PC, 한글·공백 사용자 경로, 일반 사용자/관리자, 오프라인 실행, 보안제품·파일 격리·취소 조건을 확인합니다.

Go SDK는 제작용이며 배포물에 SDK 전체를 넣지 않습니다. 최종 EXE에는 Go 표준 라이브러리가 정적으로 포함됩니다. Python·Qt는 EXE 안의 ZIP에서 꺼낸 뒤 동적으로 실행합니다. EXE 재빌드 때 `-trimpath -buildvcs=false -ldflags='-H=windowsgui -s -w -buildid='`를 사용합니다. 같은 입력과 도구로 재현할 수 있으며 OS·압축 도구가 바뀌는 경우 바이트 단위 동일성을 보장하지 않습니다.

파이썬 Windows 패키지: https://api.nuget.org/v3-flatcontainer/python/3.12.10/python.3.12.10.nupkg

빌드는 ZIP 내부 순서·타임스탬프를 고정합니다. 같은 소스·의존성·가상자료 파일과 같은 Python/zlib 환경에서는 같은 묶음을 재현하도록 했습니다. 다른 압축 도구 버전까지 바이트 단위 동일성을 보증하지 않습니다. 가상자료를 재생성하면 내부 생성시각 등으로 해시가 달라질 수 있습니다. Windows 코드서명과 배포자 인증 체계는 포함하지 않습니다.

## 인터넷 차단·통신 관찰 시험 재현

Linux의 사용자 네임스페이스를 허용하는 환경에서는 다음처럼 별도 네트워크 공간을 만들 수 있습니다. 관리자 정책에 따라 불가능할 수 있습니다. 기본 작업 디렉터리는 저장소 최상위입니다.

```sh
unshare -Urn .venv/bin/python tools/selftest.py isolated-test-new --departments 3
strace -ff -e trace=socket,connect,bind,listen,accept,accept4,sendto,sendmsg,recvfrom,recvmsg,getpeername,getsockname -o network-trace .venv/bin/python tools/selftest.py observed-test-new --departments 3
```

시스템 호출 추적에는 파일 복사 함수 sendfile을 인터넷 전송으로 잘못 세지 않도록 위 소켓 호출 목록을 사용합니다. Windows 결과를 Linux 결과로 대신하지 않습니다.

## 개발자가 지켜야 할 변경 원칙

원문값·변환값·판정·승인을 분리하고, 새 규칙·추출기 변경은 승인을 재사용하지 않도록 재처리해야 합니다. SQL이나 설정에 임의 코드를 넣지 않습니다. 실제 양식 지원은 기관 내부 정답과 새 실패 시험을 추가한 뒤 결정합니다. GUI 버튼을 막는 것만으로 충분하지 않으므로 저장·출력 함수의 검증도 유지합니다.

기본 개발 테스트의 pytest는 개발용입니다. Windows 업무 실행 패키지에는 pytest가 필요하지 않으며, 가상시험.cmd는 일반 Python selftest 도구를 사용합니다. 새 라이브러리 추가 시 오프라인 포함·라이선스·통신 시도·취약점 점검을 다시 해야 합니다.
