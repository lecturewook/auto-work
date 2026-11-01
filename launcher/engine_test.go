package main

import (
	"archive/zip"
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"testing"
)

func fixture(t *testing.T, extra map[string]string) []byte {
	t.Helper()
	files := map[string]string{"runtime/python.exe": "fake executable for unpack unit test only", "runtime/python312.dll": "fake DLL", "run_app.py": "# synthetic", "run_web.py": "# web fixture", "budget_offline/privileges.py": "# guard fixture", "한글 폴더/공백 이름.txt": "가상내용"}
	for k, v := range extra {
		files[k] = v
	}
	m := manifest{App: "0.1.2", Mode: "standard-user-only", Files: make(map[string]string)}
	for k, v := range files {
		h := sha256.Sum256([]byte(v))
		m.Files[k] = hex.EncodeToString(h[:])
	}
	data, _ := json.Marshal(m)
	files["PACKAGE_MANIFEST.json"] = string(data)
	var out bytes.Buffer
	z := zip.NewWriter(&out)
	for name, body := range files {
		w, err := z.Create(name)
		if err != nil {
			t.Fatal(err)
		}
		w.Write([]byte(body))
	}
	if err := z.Close(); err != nil {
		t.Fatal(err)
	}
	return out.Bytes()
}

func TestPrepareUnicodeCacheWithoutPythonOrPath(t *testing.T) {
	t.Setenv("PATH", "")
	b, err := openBundle(fixture(t, nil))
	if err != nil {
		t.Fatal(err)
	}
	base := filepath.Join(t.TempDir(), "일반 사용자", "공백 폴더")
	root, err := b.prepare(base, nil)
	if err != nil {
		t.Fatal(err)
	}
	if err = b.validate(root, nil); err != nil {
		t.Fatal(err)
	}
	if body, err := os.ReadFile(filepath.Join(root, "한글 폴더", "공백 이름.txt")); err != nil || string(body) != "가상내용" {
		t.Fatalf("UTF8 file mismatch: %s %v", body, err)
	}
	again, err := b.prepare(base, nil)
	if err != nil || again != root {
		t.Fatalf("cache reuse: %s %v", again, err)
	}
}

func TestPreparedFilesExact(t *testing.T) {
	b, err := openBundle(fixture(t, nil))
	if err != nil {
		t.Fatal(err)
	}
	root, err := b.prepare(t.TempDir(), nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(b.files) != 7 {
		t.Fatal(len(b.files))
	}
	if _, err = os.Stat(filepath.Join(root, "runtime", "python.exe")); err != nil {
		t.Fatal(err)
	}
}

func TestChangedOrMissingRuntimeStopsInsteadOfRecreating(t *testing.T) {
	for _, action := range []string{"changed", "missing", "extra"} {
		t.Run(action, func(t *testing.T) {
			b, err := openBundle(fixture(t, nil))
			if err != nil {
				t.Fatal(err)
			}
			base := t.TempDir()
			root, err := b.prepare(base, nil)
			if err != nil {
				t.Fatal(err)
			}
			runtime := filepath.Join(root, "runtime", "python.exe")
			switch action {
			case "changed":
				os.WriteFile(runtime, []byte("altered"), 0600)
			case "missing":
				os.Remove(runtime)
			case "extra":
				os.WriteFile(filepath.Join(root, "runtime", "sitecustomize.py"), []byte("unsafe"), 0600)
			}
			if _, err = b.prepare(base, nil); err == nil {
				t.Fatal("must block modified runtime")
			}
			if action == "missing" {
				if _, err = os.Stat(runtime); !os.IsNotExist(err) {
					t.Fatal("silently recreated potentially quarantined runtime")
				}
			}
		})
	}
}

func TestCancelKeepsNoPartialApplication(t *testing.T) {
	b, err := openBundle(fixture(t, nil))
	if err != nil {
		t.Fatal(err)
	}
	base := t.TempDir()
	_, err = b.prepare(base, func(done, total int, message string) bool { return done < 2 })
	if !errors.Is(err, errCancelled) {
		t.Fatal(err)
	}
	entries, err := os.ReadDir(base)
	if err != nil || len(entries) != 0 {
		t.Fatalf("partial files left: %v %v", entries, err)
	}
}

func TestUnsafeNamesAndCaseCollisionsRejected(t *testing.T) {
	for _, name := range []string{"../outside", "/absolute", "C:/drive", "folder\\escape", "CON.txt", "a/../b", "trail.", "AUX", "folder /file", "RUN_APP.PY"} {
		t.Run(name, func(t *testing.T) {
			if _, err := openBundle(fixture(t, map[string]string{name: "bad"})); err == nil {
				t.Fatal("unsafe path accepted")
			}
		})
	}
}

func TestLinksRejected(t *testing.T) {
	b, err := openBundle(fixture(t, nil))
	if err != nil {
		t.Fatal(err)
	}
	base := t.TempDir()
	outside := t.TempDir()
	link := filepath.Join(base, "link")
	if err = os.Symlink(outside, link); err != nil {
		t.Skip(err)
	}
	if _, err = b.prepare(link, nil); err == nil {
		t.Fatal("symlink accepted")
	}
}

func TestExistingVersionIsNotOverwritten(t *testing.T) {
	first, err := openBundle(fixture(t, nil))
	if err != nil {
		t.Fatal(err)
	}
	second, err := openBundle(fixture(t, map[string]string{"new.txt": "new version"}))
	if err != nil {
		t.Fatal(err)
	}
	base := t.TempDir()
	root1, err := first.prepare(base, nil)
	if err != nil {
		t.Fatal(err)
	}
	root2, err := second.prepare(base, nil)
	if err != nil {
		t.Fatal(err)
	}
	if root1 == root2 {
		t.Fatal("different packages overwrote cache")
	}
	if err = first.validate(root1, nil); err != nil {
		t.Fatal(err)
	}
}

func TestInvalidManifestOrCorruptArchive(t *testing.T) {
	if _, err := openBundle([]byte("broken")); err == nil {
		t.Fatal("corrupt input accepted")
	}
	var out bytes.Buffer
	z := zip.NewWriter(&out)
	w, _ := z.Create("PACKAGE_MANIFEST.json")
	w.Write([]byte(`{"app":"0.1.2","files":{}}`))
	z.Close()
	if _, err := openBundle(out.Bytes()); err == nil {
		t.Fatal("bad manifest accepted")
	}
}

// Optional real payload integration. The payload is not a fake Python file.
func TestRealReleasePayload(t *testing.T) {
	p := os.Getenv("BUDGET_TEST_PAYLOAD")
	if p == "" {
		t.Skip("real payload path not supplied")
	}
	data, err := os.ReadFile(p)
	if err != nil {
		t.Fatal(err)
	}
	b, err := openBundle(data)
	if err != nil {
		t.Fatal(err)
	}
	base := filepath.Join(t.TempDir(), "사용자 폴더 with spaces")
	root, err := b.prepare(base, nil)
	if err != nil {
		t.Fatal(err)
	}
	if err = b.validate(root, nil); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"runtime/python.exe", "runtime/python312.dll", "runtime/Lib/site-packages/PySide6/QtWidgets.pyd"} {
		body, err := os.ReadFile(filepath.Join(root, filepath.FromSlash(name)))
		if err != nil || len(body) < 2 || string(body[:2]) != "MZ" {
			t.Fatalf("real Windows executable missing: %s", name)
		}
	}
}
