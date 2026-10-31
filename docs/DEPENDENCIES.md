# 의존성·버전·라이선스

업무 PC에서 라이브러리를 내려받지 않습니다. Windows 묶음의 runtime 폴더에 아래 실행 의존성을 포함합니다. 이 목록은 최신 버전이나 보안 인증 목록이 아닙니다. 고정한 버전의 알려진 취약점·기관 허용 여부를 도입 전에 별도로 확인해야 합니다.

| 구성요소 | 버전 | 용도 | 라이선스 |
|---|---|---|---|
| Go 시작 도구/표준 라이브러리 | 1.27.3 | Python 없이 실행·권한 검사·내장 ZIP 준비. SDK는 제작 PC에서만 사용 | BSD-3-Clause, third_party/Go-LICENSE.txt |
| CPython Windows x64 | 3.12.10 | 실행 엔진, SQLite·표준 라이브러리 | PSF 및 동봉 제3자 고지 |
| PySide6-Essentials / Qt | 6.8.3 | 데스크톱 화면 | LGPL-3.0 또는 GPL-2.0/GPL-3.0 등 배포 구성별 조건 |
| shiboken6 | 6.8.3 | PySide 바인딩 | LGPL-3.0 또는 GPL-2.0/GPL-3.0 |
| openpyxl | 3.1.5 | XLSX 읽기·쓰기 | MIT |
| et-xmlfile | 2.0.0 | XLSX XML 쓰기 | MIT·동봉 Python 고지 |
| defusedxml | 0.7.1 | XML 외부 개체 공격 방어 | PSF |
| olefile | 0.47 | HWP 5 OLE 구조 읽기 | BSD |
| pytest (개발만) | 8.3.5 | 기능 시험 | MIT |

Windows 패키지에는 Qt가 배포하는 Microsoft Visual C++ 런타임 DLL과 CPython이 배포하는 OpenSSL·SQLite 등도 포함됩니다. 각 배포물의 원본 라이선스와 고지문을 보존합니다. 실행 가능한 전체 라이브러리는 `runtime/Lib/site-packages`, 고지는 `third_party`와 각 dist-info 폴더에 있습니다. 이 시험판 소스는 MIT입니다.

PySide/Qt는 DLL을 동적으로 불러오며 정적으로 링크하지 않았습니다. 단일 EXE에는 라이브러리 파일들이 압축되어 들어 있고 사용자 로컬 폴더에 준비한 다음 동적으로 불러옵니다. 이용자는 해당 라이선스에 따라 라이브러리를 교체하고 수정·디버깅할 수 있습니다. 그러면 내부 파일 해시가 달라지므로 개발용 소스와 빌드 스크립트로 변경한 묶음의 매니페스트를 새로 만들어 시험해야 합니다. 라이브러리 수정·디버깅을 위한 역공학을 금지하지 않습니다. 이 안내는 원본 라이선스 조건을 대체하지 않습니다.

라이브러리의 해당 버전 소스·라이선스 출처입니다. **개발자가 자료를 확보할 때 사용하는 주소이며 프로그램이 업무 중 접속하지 않습니다.** 오프라인 보관이 필요한 기관은 반입 담당자가 대응 소스도 별도로 확보해야 합니다.

- CPython: https://github.com/python/cpython/tree/v3.12.10
- PySide/shiboken: https://github.com/qtproject/pyside-pyside-setup/tree/v6.8.3
- Qt base: https://github.com/qt/qtbase/tree/v6.8.3
- Qt 전체 버전별 구성: https://github.com/qt/qt5/tree/v6.8.3
- openpyxl 3.1.5: https://pypi.org/project/openpyxl/3.1.5/
- et-xmlfile 2.0.0: https://pypi.org/project/et-xmlfile/2.0.0/
- defusedxml: https://github.com/tiran/defusedxml/tree/v0.7.1
- olefile: https://github.com/decalage2/olefile/tree/v0.47

DEPENDENCY_HASHES.json에 파일별 공식 다운로드 URL·SHA-256을 기록했습니다. 6개 Python wheel은 공식 PyPI JSON의 해시와 대조했습니다. CPython NuGet 파일은 공식 HTTPS로 받았고 다운로드 내용의 SHA-256을 기록했으나 NuGet 서명·Windows Authenticode 검증을 이 Linux 환경에서 수행하지 않았습니다. 최종 ZIP의 SHA-256 또한 코드서명이나 배포자 인증을 대신하지 않습니다.

Go SDK의 공식 URL·SHA-256·소스 URL은 `BUILD_TOOLCHAIN.json`에 있습니다. 공식 HTTPS 배포 메타데이터의 해시로 Linux x64 SDK를 검증했습니다. Go 외부 모듈 의존성은 없습니다.
