package main

// The launcher only unpacks the embedded, offline application. No downloader,
// shell command, URL handler, or network client is used here.
import (
	"archive/zip"
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path"
	"path/filepath"
	"strings"
)

var errCancelled = errors.New("준비를 취소했습니다")

type manifest struct {
	App   string            `json:"app"`
	Mode  string            `json:"execution_mode"`
	Files map[string]string `json:"files"`
}

type bundle struct {
	files         map[string]*zip.File
	manifest      manifest
	manifestBytes []byte
	id            string
	total         uint64
}

type progress func(done, total int, message string) bool

func safeName(name string) bool {
	if name == "" || path.Clean(name) != name || strings.HasPrefix(name, "/") || strings.ContainsAny(name, "\\:<>\"|?*\x00") {
		return false
	}
	for _, part := range strings.Split(name, "/") {
		if part == "" || part == "." || part == ".." || strings.TrimRight(part, ". ") != part {
			return false
		}
		for _, c := range part {
			if c < 32 {
				return false
			}
		}
		base := strings.ToUpper(strings.SplitN(part, ".", 2)[0])
		if base == "CON" || base == "PRN" || base == "AUX" || base == "NUL" || (len(base) == 4 && (strings.HasPrefix(base, "COM") || strings.HasPrefix(base, "LPT")) && base[3] >= '1' && base[3] <= '9') {
			return false
		}
	}
	return true
}

func openBundle(data []byte) (*bundle, error) {
	r, err := zip.NewReader(bytes.NewReader(data), int64(len(data)))
	if err != nil {
		return nil, fmt.Errorf("내장 파일 묶음 손상: %w", err)
	}
	b := &bundle{files: make(map[string]*zip.File)}
	seen := make(map[string]bool)
	for _, f := range r.File {
		if !safeName(f.Name) || seen[strings.ToLower(f.Name)] || !f.Mode().IsRegular() {
			return nil, errors.New("내장 파일 경로 또는 형식이 안전하지 않습니다")
		}
		seen[strings.ToLower(f.Name)] = true
		b.total += f.UncompressedSize64
		if len(seen) > 10000 || f.UncompressedSize64 > 512<<20 || b.total > 1<<30 {
			return nil, errors.New("내장 파일 크기 제한을 넘었습니다")
		}
		b.files[f.Name] = f
	}
	mf, ok := b.files["PACKAGE_MANIFEST.json"]
	if !ok || mf.UncompressedSize64 > 4<<20 {
		return nil, errors.New("내장 파일 목록이 없거나 너무 큽니다")
	}
	s, err := mf.Open()
	if err != nil {
		return nil, err
	}
	b.manifestBytes, err = io.ReadAll(io.LimitReader(s, 4<<20))
	s.Close()
	if err != nil {
		return nil, err
	}
	if err = json.Unmarshal(b.manifestBytes, &b.manifest); err != nil {
		return nil, errors.New("내장 파일 목록을 읽지 못했습니다")
	}
	if b.manifest.App == "" || !safeName(b.manifest.App) || strings.Contains(b.manifest.App, "/") || b.manifest.Mode != "standard-user-only" || len(b.manifest.Files) != len(b.files)-1 {
		return nil, errors.New("내장 파일 목록 또는 실행 정책이 올바르지 않습니다")
	}
	for name, hash := range b.manifest.Files {
		if _, ok := b.files[name]; !ok || name == "PACKAGE_MANIFEST.json" || !safeName(name) {
			return nil, errors.New("내장 파일 목록이 일치하지 않습니다")
		}
		decoded, err := hex.DecodeString(hash)
		if err != nil || len(decoded) != sha256.Size {
			return nil, errors.New("내장 파일 해시 형식이 올바르지 않습니다")
		}
	}
	for _, name := range []string{"runtime/python.exe", "runtime/python312.dll", "run_app.py", "budget_offline/privileges.py"} {
		if _, ok := b.files[name]; !ok {
			return nil, fmt.Errorf("필수 실행 파일 없음: %s", name)
		}
	}
	h := sha256.Sum256(data)
	b.id = b.manifest.App + "-" + hex.EncodeToString(h[:])[:16]
	return b, nil
}

func noLinks(p string) error {
	p, err := filepath.Abs(p)
	if err != nil {
		return err
	}
	for {
		info, err := os.Lstat(p)
		if err == nil && info.Mode()&os.ModeSymlink != 0 {
			return errors.New("연결 폴더에는 프로그램을 준비할 수 없습니다")
		}
		if err != nil && !os.IsNotExist(err) {
			return err
		}
		parent := filepath.Dir(p)
		if parent == p {
			break
		}
		p = parent
	}
	return nil
}

func report(update progress, done, total int, message string) error {
	if update != nil && !update(done, total, message) {
		return errCancelled
	}
	return nil
}

func (b *bundle) expectedHash(name string) string {
	if name == "PACKAGE_MANIFEST.json" {
		h := sha256.Sum256(b.manifestBytes)
		return hex.EncodeToString(h[:])
	}
	return b.manifest.Files[name]
}

func (b *bundle) validate(root string, update progress) error {
	if err := noLinks(root); err != nil {
		return err
	}
	count := 0
	err := filepath.WalkDir(root, func(p string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.Type()&os.ModeSymlink != 0 {
			return errors.New("프로그램 폴더에 연결 파일이 있습니다")
		}
		if d.IsDir() {
			return nil
		}
		rel, err := filepath.Rel(root, p)
		if err != nil {
			return err
		}
		name := filepath.ToSlash(rel)
		zf, ok := b.files[name]
		if !ok {
			return fmt.Errorf("프로그램 폴더에 추가 파일이 있습니다: %s", name)
		}
		info, err := d.Info()
		if err != nil {
			return err
		}
		if !info.Mode().IsRegular() || uint64(info.Size()) != zf.UncompressedSize64 {
			return fmt.Errorf("프로그램 파일 크기 또는 형식 변경: %s", name)
		}
		file, err := os.Open(p)
		if err != nil {
			return err
		}
		h := sha256.New()
		_, err = io.Copy(h, file)
		file.Close()
		if err != nil {
			return err
		}
		if hex.EncodeToString(h.Sum(nil)) != b.expectedHash(name) {
			return fmt.Errorf("프로그램 파일 해시 불일치: %s", name)
		}
		count++
		return report(update, count, len(b.files), "실행 파일을 확인하고 있습니다")
	})
	if err != nil {
		return err
	}
	if count != len(b.files) {
		return errors.New("프로그램 파일이 누락되었습니다. 보안 프로그램의 격리 여부를 기관 담당자에게 확인하세요")
	}
	return nil
}

func (b *bundle) prepare(base string, update progress) (string, error) {
	if err := noLinks(base); err != nil {
		return "", err
	}
	if err := os.MkdirAll(base, 0700); err != nil {
		return "", err
	}
	root := filepath.Join(base, b.id)
	if _, err := os.Lstat(root); err == nil {
		if err = b.validate(root, update); err != nil {
			return "", fmt.Errorf("기존 프로그램 파일 확인 실패. 파일을 임의로 복구하거나 보안 차단을 해제하지 말고 기관 담당자에게 확인하세요. 위치: %s\n%w", root, err)
		}
		return root, nil
	} else if !os.IsNotExist(err) {
		return "", err
	}
	stage, err := os.MkdirTemp(base, ".preparing-")
	if err != nil {
		return "", err
	}
	defer os.RemoveAll(stage)
	i := 0
	for _, f := range b.files {
		if err = report(update, i, len(b.files), "내장 파일을 PC 안에 준비하고 있습니다"); err != nil {
			return "", err
		}
		target := filepath.Join(stage, filepath.FromSlash(f.Name))
		if err = os.MkdirAll(filepath.Dir(target), 0700); err != nil {
			return "", err
		}
		src, err := f.Open()
		if err != nil {
			return "", err
		}
		dst, err := os.OpenFile(target, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
		if err != nil {
			src.Close()
			return "", err
		}
		h := sha256.New()
		n, copyErr := io.Copy(io.MultiWriter(dst, h), io.LimitReader(src, int64(f.UncompressedSize64)+1))
		src.Close()
		closeErr := dst.Close()
		if copyErr != nil {
			return "", copyErr
		}
		if closeErr != nil {
			return "", closeErr
		}
		if uint64(n) != f.UncompressedSize64 || hex.EncodeToString(h.Sum(nil)) != b.expectedHash(f.Name) {
			return "", fmt.Errorf("내장 파일 검증 실패: %s", f.Name)
		}
		i++
	}
	if err = report(update, i, len(b.files), "프로그램 준비가 끝났습니다"); err != nil {
		return "", err
	}
	if err = os.Rename(stage, root); err != nil {
		// Another instance may have completed the same immutable cache.
		if validateErr := b.validate(root, update); validateErr == nil {
			return root, nil
		}
		return "", err
	}
	return root, nil
}
