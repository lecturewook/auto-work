package main

import (
	"errors"
	"fmt"
	"strings"
)

// Only the native Windows adapter can mark these facts as verified. No caller
// argument or environment variable can grant permission to process documents.
type tokenFacts struct {
	Verified      bool
	User          string
	Session       uint32
	Elevated      bool
	Integrity     uint32
	Administrator bool
	PowerUser     bool
	UIAccess      bool
}

func (f tokenFacts) standard() bool {
	return f.Verified && f.User != "" && f.Session != 0 &&
		f.User != "S-1-5-18" && f.User != "S-1-5-19" && f.User != "S-1-5-20" &&
		!f.Elevated && f.Integrity <= 0x2000 && !f.Administrator && !f.PowerUser && !f.UIAccess
}

func sameLimitedUser(original, candidate tokenFacts) error {
	if !original.Verified || !candidate.standard() {
		return errors.New("일반 사용자 권한 확인 실패")
	}
	if original.User != candidate.User || original.Session != candidate.Session {
		return errors.New("사용자 또는 로그인 세션이 달라 전환 중단")
	}
	return nil
}

type startupPlatform interface {
	current() (tokenFacts, error)
	// Must validate BOTH the candidate token and the suspended child process
	// before resuming it. A nil return means the standard child was resumed.
	relaunch(method string, original tokenFacts) error
}

var limitedMethods = []string{"UAC", "바탕화면", "Windows 기본 사용자"}

func guardedStartup(args []string, platform startupPlatform, work func() error) error {
	child := len(args) == 1 && args[0] == "--standard-child"
	if len(args) != 0 && !child {
		return errors.New("지원하지 않는 실행 인수입니다. 실행 파일을 더블클릭하세요")
	}
	current, err := platform.current()
	if err != nil || !current.Verified {
		return fmt.Errorf("실행 권한을 확인할 수 없어 자료를 열지 않았습니다. 기관 담당자에게 오류 코드를 알려주세요.\n%v", err)
	}
	if current.standard() {
		return work()
	}
	if child {
		return errors.New("일반 권한으로 다시 시작했지만 권한 검사를 통과하지 못했습니다. 자료는 열지 않았습니다.\n기관 담당자가 실행 파일의 호환성 설정과 사용자 정책을 확인해야 합니다")
	}
	var failures []string
	for _, method := range limitedMethods {
		if err := platform.relaunch(method, current); err == nil {
			return nil // Elevated parent does not unpack, log, read data, or wait.
		} else {
			failures = append(failures, method+": "+err.Error())
		}
	}
	return fmt.Errorf("일반 사용자 권한으로 자동 전환하지 못해 자료를 열지 않았습니다.\n기관 담당자가 일반 사용자 계정, 호환성의 관리자 실행 설정, 실행 허용 정책을 확인해야 합니다.\n보안 기능을 끄거나 관리자 실행으로 우회하지 마세요.\n\n%s", strings.Join(failures, "\n"))
}
