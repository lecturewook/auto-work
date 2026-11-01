//go:build windows

package main

import (
	"encoding/binary"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"syscall"
	"unsafe"
)

// These APIs only REDUCE rights. No RunAs verb, credentials, registry changes,
// privilege enabling, policy exemptions or network services are used.
type windowsStartup struct{}

func apiFailure(name string, err error) error {
	if code, ok := err.(syscall.Errno); ok {
		return fmt.Errorf("%s (Windows 코드 %d)", name, uint32(code))
	}
	return fmt.Errorf("%s 확인 실패", name)
}

func tokenData(token syscall.Token, class uint32) ([]byte, error) {
	var size uint32
	err := syscall.GetTokenInformation(token, class, nil, 0, &size)
	if err != syscall.ERROR_INSUFFICIENT_BUFFER || size == 0 || size > 1024*1024 {
		return nil, apiFailure("GetTokenInformation", err)
	}
	data := make([]byte, size)
	if err = syscall.GetTokenInformation(token, class, &data[0], size, &size); err != nil {
		return nil, apiFailure("GetTokenInformation", err)
	}
	if size == 0 || int(size) > len(data) {
		return nil, errors.New("권한 정보 길이 오류")
	}
	return data[:size], nil
}

func tokenUint(token syscall.Token, class uint32) (uint32, error) {
	data, err := tokenData(token, class)
	if err != nil {
		return 0, err
	}
	if len(data) != 4 {
		return 0, errors.New("권한 정보 형식 오류")
	}
	return binary.LittleEndian.Uint32(data), nil
}

func inspectToken(token syscall.Token) (tokenFacts, error) {
	f := tokenFacts{}
	u, err := token.GetTokenUser()
	if err != nil {
		return f, apiFailure("TokenUser", err)
	}
	f.User, err = u.User.Sid.String()
	if err != nil {
		return f, apiFailure("TokenUser SID", err)
	}
	f.Session, err = tokenUint(token, syscall.TokenSessionId)
	if err != nil {
		return f, err
	}
	elevation, err := tokenUint(token, syscall.TokenElevation)
	if err != nil || elevation > 1 {
		return f, errors.New("권한 상승 여부 확인 실패")
	}
	f.Elevated = elevation != 0
	ui, err := tokenUint(token, syscall.TokenUIAccess)
	if err != nil || ui > 1 {
		return f, errors.New("화면 접근 권한 확인 실패")
	}
	f.UIAccess = ui != 0
	label, err := tokenData(token, syscall.TokenIntegrityLevel)
	if err != nil || len(label) < int(unsafe.Sizeof(syscall.SIDAndAttributes{})) {
		return f, errors.New("무결성 수준 확인 실패")
	}
	sid := (*syscall.SIDAndAttributes)(unsafe.Pointer(&label[0])).Sid
	if sid == nil {
		return f, errors.New("무결성 SID 없음")
	}
	integrity, err := sid.String()
	runtime.KeepAlive(label)
	if err != nil || !strings.HasPrefix(integrity, "S-1-16-") {
		return f, errors.New("무결성 SID 확인 실패")
	}
	rid, err := strconv.ParseUint(strings.TrimPrefix(integrity, "S-1-16-"), 10, 32)
	if err != nil {
		return f, errors.New("무결성 RID 확인 실패")
	}
	f.Integrity = uint32(rid)
	groups, err := tokenData(token, syscall.TokenGroups)
	if err != nil || len(groups) < 4 {
		return f, errors.New("사용자 그룹 확인 실패")
	}
	count := int(binary.LittleEndian.Uint32(groups))
	type groupHeader struct {
		Count uint32
		First syscall.SIDAndAttributes
	}
	offset, stride := int(unsafe.Offsetof(groupHeader{}.First)), int(unsafe.Sizeof(syscall.SIDAndAttributes{}))
	if count > 4096 || offset+count*stride > len(groups) {
		return f, errors.New("사용자 그룹 길이 오류")
	}
	for i := 0; i < count; i++ {
		group := (*syscall.SIDAndAttributes)(unsafe.Pointer(&groups[offset+i*stride]))
		if group.Attributes&0x4 == 0 { // SE_GROUP_ENABLED; deny-only does not grant access.
			continue
		}
		if group.Sid == nil {
			return f, errors.New("사용자 그룹 SID 없음")
		}
		name, err := group.Sid.String()
		if err != nil {
			return f, apiFailure("Group SID", err)
		}
		f.Administrator = f.Administrator || name == "S-1-5-32-544"
		f.PowerUser = f.PowerUser || name == "S-1-5-32-547"
	}
	runtime.KeepAlive(groups)
	f.Verified = true
	return f, nil
}

func (windowsStartup) current() (tokenFacts, error) {
	token, err := syscall.OpenCurrentProcessToken()
	if err != nil {
		return tokenFacts{}, apiFailure("OpenProcessToken", err)
	}
	defer token.Close()
	return inspectToken(token)
}

func duplicatePrimary(token syscall.Token) (syscall.Token, error) {
	var primary syscall.Token
	// QUERY | DUPLICATE | ASSIGN_PRIMARY | ADJUST_DEFAULT. The latter permits
	// lowering the mandatory integrity label on our new private token only.
	ok, _, err := advapi32.NewProc("DuplicateTokenEx").Call(uintptr(token), 0x8B, 0, 2, 1, uintptr(unsafe.Pointer(&primary)))
	if ok == 0 {
		return 0, apiFailure("DuplicateTokenEx", err)
	}
	return primary, nil
}

func linkedPrimary() (syscall.Token, error) {
	current, err := syscall.OpenCurrentProcessToken()
	if err != nil {
		return 0, apiFailure("OpenProcessToken", err)
	}
	defer current.Close()
	data, err := tokenData(current, syscall.TokenLinkedToken)
	if err != nil {
		return 0, err
	}
	if len(data) != int(unsafe.Sizeof(syscall.Token(0))) {
		return 0, errors.New("UAC 연결 권한 없음")
	}
	linked := *(*syscall.Token)(unsafe.Pointer(&data[0]))
	defer linked.Close()
	return duplicatePrimary(linked)
}

func shellPrimary() (syscall.Token, error) {
	shell, _, _ := user32.NewProc("GetShellWindow").Call()
	if shell == 0 {
		return 0, errors.New("로그인 바탕화면 없음")
	}
	var pid uint32
	thread, _, err := user32.NewProc("GetWindowThreadProcessId").Call(shell, uintptr(unsafe.Pointer(&pid)))
	if thread == 0 || pid == 0 {
		return 0, apiFailure("GetWindowThreadProcessId", err)
	}
	process, err := syscall.OpenProcess(0x1000, false, pid)
	if err != nil {
		return 0, apiFailure("OpenProcess", err)
	}
	defer syscall.CloseHandle(process)
	var token syscall.Token
	if err = syscall.OpenProcessToken(process, syscall.TOKEN_QUERY|syscall.TOKEN_DUPLICATE, &token); err != nil {
		return 0, apiFailure("OpenProcessToken", err)
	}
	defer token.Close()
	return duplicatePrimary(token)
}

func basicUserPrimary() (syscall.Token, error) {
	process, err := syscall.GetCurrentProcess()
	if err != nil {
		return 0, apiFailure("GetCurrentProcess", err)
	}
	var current syscall.Token
	err = syscall.OpenProcessToken(process, syscall.TOKEN_QUERY|syscall.TOKEN_DUPLICATE, &current)
	if err != nil {
		return 0, apiFailure("OpenProcessToken", err)
	}
	defer current.Close()
	var level syscall.Handle
	// Scope USER=2, NORMALUSER=0x20000, SAFER_LEVEL_OPEN=1.
	ok, _, err := advapi32.NewProc("SaferCreateLevel").Call(2, 0x20000, 1, uintptr(unsafe.Pointer(&level)), 0)
	if ok == 0 {
		return 0, apiFailure("SaferCreateLevel", err)
	}
	defer advapi32.NewProc("SaferCloseLevel").Call(uintptr(level))
	var restricted syscall.Token
	// Flags 0: AppLocker and Software Restriction Policies remain enforced.
	ok, _, err = advapi32.NewProc("SaferComputeTokenFromLevel").Call(uintptr(level), uintptr(current), uintptr(unsafe.Pointer(&restricted)), 0, 0)
	if ok == 0 || restricted == 0 {
		return 0, apiFailure("SaferComputeTokenFromLevel", err)
	}
	defer restricted.Close()
	primary, err := duplicatePrimary(restricted)
	if err != nil {
		return 0, err
	}
	// SAFER removes administrator rights; it need not lower the integrity label.
	// Set medium on this new token. The complete token is inspected afterwards.
	sid, err := syscall.StringToSid("S-1-16-8192")
	if err != nil {
		primary.Close()
		return 0, apiFailure("Medium SID", err)
	}
	label := syscall.SIDAndAttributes{Sid: sid, Attributes: 0x20}
	ok, _, err = advapi32.NewProc("SetTokenInformation").Call(uintptr(primary), syscall.TokenIntegrityLevel,
		uintptr(unsafe.Pointer(&label)), unsafe.Sizeof(label)+uintptr(sid.Len()))
	runtime.KeepAlive(sid)
	if ok == 0 {
		primary.Close()
		return 0, apiFailure("SetTokenInformation medium", err)
	}
	return primary, nil
}

func (windowsStartup) relaunch(method string, original tokenFacts) error {
	var token syscall.Token
	var err error
	switch method {
	case "UAC":
		token, err = linkedPrimary()
	case "바탕화면":
		token, err = shellPrimary()
	case "Windows 기본 사용자":
		token, err = basicUserPrimary()
	default:
		return errors.New("알 수 없는 권한 전환 방법")
	}
	if err != nil {
		return err
	}
	defer token.Close()
	facts, err := inspectToken(token)
	if err != nil {
		return err
	}
	if err = sameLimitedUser(original, facts); err != nil {
		return err
	}
	return startLimitedChild(token, original)
}

func startLimitedChild(token syscall.Token, original tokenFacts) error {
	executable, err := os.Executable()
	if err != nil || !filepath.IsAbs(executable) || strings.HasPrefix(executable, "\\\\") {
		return errors.New("PC 내부 실행 파일 위치 확인 실패")
	}
	// Absolute system DLL path, independent of PATH, CWD and inherited env vars.
	var system [32768]uint16
	n, _, err := kernel32.NewProc("GetSystemDirectoryW").Call(uintptr(unsafe.Pointer(&system[0])), uintptr(len(system)))
	if n == 0 || n >= uintptr(len(system)) {
		return apiFailure("GetSystemDirectoryW", err)
	}
	userenv := syscall.NewLazyDLL(filepath.Join(syscall.UTF16ToString(system[:n]), "userenv.dll"))
	var environment uintptr
	ok, _, err := userenv.NewProc("CreateEnvironmentBlock").Call(uintptr(unsafe.Pointer(&environment)), uintptr(token), 0)
	if ok == 0 {
		return apiFailure("CreateEnvironmentBlock", err)
	}
	defer userenv.NewProc("DestroyEnvironmentBlock").Call(environment)
	startup := syscall.StartupInfo{Desktop: wide("winsta0\\default")}
	startup.Cb = uint32(unsafe.Sizeof(startup))
	var process syscall.ProcessInformation
	command := wide(syscall.EscapeArg(executable) + " --standard-child")
	// CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT. No handle inheritance.
	ok, _, err = advapi32.NewProc("CreateProcessWithTokenW").Call(uintptr(token), 0,
		uintptr(unsafe.Pointer(wide(executable))), uintptr(unsafe.Pointer(command)), 0x404,
		environment, uintptr(unsafe.Pointer(wide(filepath.Dir(executable)))),
		uintptr(unsafe.Pointer(&startup)), uintptr(unsafe.Pointer(&process)))
	if ok == 0 {
		return apiFailure("CreateProcessWithTokenW", err)
	}
	defer syscall.CloseHandle(process.Process)
	defer syscall.CloseHandle(process.Thread)
	resumed := false
	defer func() {
		if !resumed {
			syscall.TerminateProcess(process.Process, 1)
		}
	}()
	var childToken syscall.Token
	if err = syscall.OpenProcessToken(process.Process, syscall.TOKEN_QUERY, &childToken); err != nil {
		return apiFailure("Child OpenProcessToken", err)
	}
	defer childToken.Close()
	child, err := inspectToken(childToken)
	if err != nil {
		return err
	}
	if err = sameLimitedUser(original, child); err != nil {
		return err
	}
	previous, _, err := kernel32.NewProc("ResumeThread").Call(uintptr(process.Thread))
	if previous != 1 {
		return apiFailure("ResumeThread", err)
	}
	resumed = true
	return nil
}
