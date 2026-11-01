package main

import (
	"errors"
	"strings"
	"testing"
)

func ordinary() tokenFacts {
	return tokenFacts{Verified: true, User: "S-1-5-21-123-456-789-1001", Session: 1, Integrity: 0x2000}
}

func administrator() tokenFacts {
	f := ordinary()
	f.Elevated, f.Administrator, f.Integrity = true, true, 0x3000
	return f
}

type fakeStartup struct {
	facts      tokenFacts
	queryError error
	calls      []string
	launch     func(string, tokenFacts) error
}

func (f *fakeStartup) current() (tokenFacts, error) { return f.facts, f.queryError }
func (f *fakeStartup) relaunch(method string, original tokenFacts) error {
	f.calls = append(f.calls, method)
	if f.launch != nil {
		return f.launch(method, original)
	}
	return errors.New("simulated Windows error 1314")
}

func TestStandardUserStartsWorkDirectly(t *testing.T) {
	p := &fakeStartup{facts: ordinary()}
	called := 0
	err := guardedStartup(nil, p, func() error { called++; return nil })
	if err != nil || called != 1 || len(p.calls) != 0 {
		t.Fatalf("%v work=%d calls=%v", err, called, p.calls)
	}
}

func TestElevatedParentHandsOffWithoutProcessing(t *testing.T) {
	for _, available := range limitedMethods {
		t.Run(available, func(t *testing.T) {
			p := &fakeStartup{facts: administrator(), launch: func(method string, original tokenFacts) error {
				if method != available {
					return errors.New("unavailable")
				}
				return sameLimitedUser(original, ordinary())
			}}
			err := guardedStartup(nil, p, func() error { t.Fatal("elevated work callback"); return nil })
			if err != nil || p.calls[len(p.calls)-1] != available {
				t.Fatal(err, p.calls)
			}
		})
	}
}

func TestAllRelaunchFailuresPreventAnyWork(t *testing.T) {
	p := &fakeStartup{facts: administrator()}
	err := guardedStartup(nil, p, func() error { t.Fatal("work despite failure"); return nil })
	if err == nil || !strings.Contains(err.Error(), "1314") || len(p.calls) != 3 {
		t.Fatal(err, p.calls)
	}
}

func TestUnknownRightsPreventRelaunchAndWork(t *testing.T) {
	for _, p := range []*fakeStartup{{facts: ordinary(), queryError: errors.New("query failed")}, {facts: tokenFacts{}}} {
		err := guardedStartup(nil, p, func() error { t.Fatal("unknown rights accepted"); return nil })
		if err == nil || len(p.calls) != 0 {
			t.Fatal(err, p.calls)
		}
	}
}

func TestStandardChildChecksItsOwnRights(t *testing.T) {
	p := &fakeStartup{facts: ordinary()}
	called := false
	err := guardedStartup([]string{"--standard-child"}, p, func() error { called = true; return nil })
	if err != nil || !called || len(p.calls) != 0 {
		t.Fatal(err)
	}
	p.facts = administrator()
	err = guardedStartup([]string{"--standard-child"}, p, func() error { t.Fatal("elevated child work"); return nil })
	if err == nil || len(p.calls) != 0 {
		t.Fatal("must fail without relaunch loop", err, p.calls)
	}
}

func TestUnsafeCandidateTokensAreRejected(t *testing.T) {
	cases := map[string]func(*tokenFacts){
		"unverified":             func(f *tokenFacts) { f.Verified = false },
		"other user":             func(f *tokenFacts) { f.User += "2" },
		"other session":          func(f *tokenFacts) { f.Session++ },
		"session zero":           func(f *tokenFacts) { f.Session = 0 },
		"system":                 func(f *tokenFacts) { f.User = "S-1-5-18" },
		"empty identity":         func(f *tokenFacts) { f.User = "" },
		"elevated":               func(f *tokenFacts) { f.Elevated = true },
		"high integrity":         func(f *tokenFacts) { f.Integrity = 0x3000 },
		"medium plus integrity":  func(f *tokenFacts) { f.Integrity = 0x2100 },
		"enabled administrators": func(f *tokenFacts) { f.Administrator = true },
		"enabled power users":    func(f *tokenFacts) { f.PowerUser = true },
		"UI access":              func(f *tokenFacts) { f.UIAccess = true },
	}
	for name, change := range cases {
		t.Run(name, func(t *testing.T) {
			candidate := ordinary()
			change(&candidate)
			if sameLimitedUser(administrator(), candidate) == nil {
				t.Fatal("unsafe candidate accepted")
			}
			if candidate.User == ordinary().User && candidate.Session == 1 && candidate.standard() {
				t.Fatal("unsafe current token accepted")
			}
		})
	}
	if sameLimitedUser(tokenFacts{}, ordinary()) == nil {
		t.Fatal("unknown original accepted")
	}
}

func TestLimitedChildMayNotSwitchUserOrBecomeElevated(t *testing.T) {
	for _, child := range []tokenFacts{administrator(), {Verified: true, User: "different", Session: 1, Integrity: 0x2000}} {
		p := &fakeStartup{facts: administrator(), launch: func(method string, original tokenFacts) error {
			if err := sameLimitedUser(original, ordinary()); err != nil {
				return err
			}
			return sameLimitedUser(original, child)
		}}
		err := guardedStartup(nil, p, func() error { t.Fatal("parent processed work"); return nil })
		if err == nil {
			t.Fatal("unsafe actual child accepted")
		}
	}
}

func TestArgumentCannotBypassGuard(t *testing.T) {
	for _, args := range [][]string{{"--allow-admin"}, {"--standard-child", "extra"}, {"--run-as-user"}} {
		p := &fakeStartup{facts: ordinary()}
		err := guardedStartup(args, p, func() error { t.Fatal("unknown argument accepted"); return nil })
		if err == nil || len(p.calls) != 0 {
			t.Fatal(err)
		}
	}
}

func TestWorkFailureRemainsVisible(t *testing.T) {
	want := errors.New("disk full")
	err := guardedStartup(nil, &fakeStartup{facts: ordinary()}, func() error { return want })
	if !errors.Is(err, want) {
		t.Fatal(err)
	}
}
