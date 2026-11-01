//go:build windows

package main

import (
	_ "embed"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"syscall"
	"unsafe"
)

//go:embed payload.zip
var payload []byte

var user32 = syscall.NewLazyDLL("user32.dll")
var kernel32 = syscall.NewLazyDLL("kernel32.dll")
var advapi32 = syscall.NewLazyDLL("advapi32.dll")

func wide(s string) *uint16 { p, _ := syscall.UTF16PtrFromString(s); return p }

func message(s string) {
	user32.NewProc("MessageBoxW").Call(0, uintptr(unsafe.Pointer(wide(s))), uintptr(unsafe.Pointer(wide("오프라인 예산 시험판"))), 0x10)
}

type windowClass struct {
	Size, Style                        uint32
	Procedure                          uintptr
	ClassExtra, WindowExtra            int32
	Instance, Icon, Cursor, Background uintptr
	Menu, Class                        *uint16
	SmallIcon                          uintptr
}
type winMessage struct {
	Window         uintptr
	Message        uint32
	WParam, LParam uintptr
	Time           uint32
	X, Y           int32
	Private        uint32
}
type statusWindow struct {
	window, label uintptr
	cancelled     bool
}

func createStatus() (*statusWindow, error) {
	s := &statusWindow{}
	className := wide("BudgetOfflinePreparation")
	instance, _, _ := kernel32.NewProc("GetModuleHandleW").Call(0)
	proc := syscall.NewCallback(func(hwnd, msg, w, l uintptr) uintptr {
		if msg == 0x10 {
			s.cancelled = true
			user32.NewProc("DestroyWindow").Call(hwnd)
			return 0
		}
		v, _, _ := user32.NewProc("DefWindowProcW").Call(hwnd, msg, w, l)
		return v
	})
	c := windowClass{Procedure: proc, Instance: instance, Class: className, Background: 6}
	c.Size = uint32(unsafe.Sizeof(c))
	if ok, _, _ := user32.NewProc("RegisterClassExW").Call(uintptr(unsafe.Pointer(&c))); ok == 0 {
		return nil, errors.New("준비 화면 등록에 실패했습니다")
	}
	x, _, _ := user32.NewProc("GetSystemMetrics").Call(0)
	y, _, _ := user32.NewProc("GetSystemMetrics").Call(1)
	s.window, _, _ = user32.NewProc("CreateWindowExW").Call(0, uintptr(unsafe.Pointer(className)), uintptr(unsafe.Pointer(wide("오프라인 예산 시험판 — 실행 준비"))), 0x10CA0000, (x-640)/2, (y-190)/2, 640, 190, 0, 0, instance, 0)
	if s.window == 0 {
		return nil, errors.New("준비 화면을 열 수 없습니다")
	}
	s.label, _, _ = user32.NewProc("CreateWindowExW").Call(0, uintptr(unsafe.Pointer(wide("STATIC"))), uintptr(unsafe.Pointer(wide("실행 준비 중입니다. 잠시 기다려 주세요.\r\nPython 설치와 인터넷 연결은 필요하지 않습니다."))), 0x50000000, 20, 20, 590, 105, s.window, 0, instance, 0)
	font, _, _ := syscall.NewLazyDLL("gdi32.dll").NewProc("GetStockObject").Call(17)
	user32.NewProc("SendMessageW").Call(s.label, 0x30, font, 1)
	user32.NewProc("UpdateWindow").Call(s.window)
	return s, nil
}

func (s *statusWindow) update(done, total int, text string) bool {
	text = fmt.Sprintf("%s (%d/%d)\r\nPython 설치와 인터넷 연결은 필요하지 않습니다.\r\n창을 닫으면 준비를 취소합니다.", text, done, total)
	user32.NewProc("SetWindowTextW").Call(s.label, uintptr(unsafe.Pointer(wide(text))))
	var msg winMessage
	for {
		result, _, _ := user32.NewProc("PeekMessageW").Call(uintptr(unsafe.Pointer(&msg)), 0, 0, 0, 1)
		if result == 0 {
			break
		}
		user32.NewProc("TranslateMessage").Call(uintptr(unsafe.Pointer(&msg)))
		user32.NewProc("DispatchMessageW").Call(uintptr(unsafe.Pointer(&msg)))
	}
	return !s.cancelled
}

func (s *statusWindow) close() {
	if s.window != 0 {
		user32.NewProc("DestroyWindow").Call(s.window)
		s.window = 0
	}
}

func run() error {
	return guardedStartup(os.Args[1:], windowsStartup{}, runWork)
}

func runWork() error {
	cache, err := os.UserCacheDir()
	if err != nil {
		return errors.New("일반 사용자 저장 폴더를 찾을 수 없습니다. 기관 담당자에게 확인하세요")
	}
	if len(cache) < 3 || cache[:2] == "\\\\" || cache[:2] == "//" {
		return errors.New("프로그램 준비 위치는 PC 안의 로컬 디스크여야 합니다")
	}
	drive := filepath.VolumeName(cache) + "\\"
	driveType, _, _ := kernel32.NewProc("GetDriveTypeW").Call(uintptr(unsafe.Pointer(wide(drive))))
	if driveType != 3 {
		return errors.New("사용자 저장 폴더가 로컬 고정 디스크인지 확인할 수 없습니다. 공유 드라이브를 사용할 수 없습니다")
	}
	base := filepath.Join(cache, "BudgetOffline", "app")
	status, err := createStatus()
	if err != nil {
		return err
	}
	defer status.close()
	b, err := openBundle(payload)
	if err != nil {
		return err
	}
	root, err := b.prepare(base, status.update)
	if err != nil {
		return fmt.Errorf("실행 준비에 실패했습니다. 사용자 폴더 권한, 남은 공간, 보안 프로그램 격리 여부를 확인하세요.\n\n%w", err)
	}
	status.close()
	logs := filepath.Join(cache, "BudgetOffline", "logs")
	if err = noLinks(logs); err != nil {
		return err
	}
	if err = os.MkdirAll(logs, 0700); err != nil {
		return err
	}
	log, err := os.CreateTemp(logs, "startup-*.log")
	if err != nil {
		return err
	}
	defer log.Close()
	cmd := exec.Command(filepath.Join(root, "runtime", "python.exe"), "-E", "-s", "-B", filepath.Join(root, "run_web.py"))
	cmd.Dir = root
	cmd.Stdout = log
	cmd.Stderr = log
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000}
	if err = cmd.Run(); err != nil {
		return fmt.Errorf("화면을 시작하지 못했습니다. Python을 별도로 설치하거나 관리자 권한으로 실행하지 마세요.\n보안 프로그램 격리 여부를 기관 담당자에게 확인하세요.\n오류: %v\nPC 안의 시작 기록: %s", err, log.Name())
	}
	return nil
}

func main() {
	runtime.LockOSThread()
	if err := run(); err != nil && !errors.Is(err, errCancelled) {
		message(err.Error())
		os.Exit(1)
	}
}
