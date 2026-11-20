package ifl

import (
	"strings"
	"testing"
)

func TestNormalizeEmail(t *testing.T) {
	cases := []struct {
		name, in, want string
		ok             bool
	}{
		{"plain", "gm@example.com", "gm@example.com", true},
		{"lowercased", "GM@Example.COM", "gm@example.com", true},
		{"trimmed", "  gm@example.com \n", "gm@example.com", true},
		{"empty", "", "", false},
		{"blank", "   ", "", false},
		{"no at", "gm.example.com", "", false},
		{"display name", "GM <gm@example.com>", "", false},
		{"angle brackets", "<gm@example.com>", "", false},
		{"too long", strings.Repeat("a", 120) + "@example.com", "", false},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got, ok := NormalizeEmail(c.in)
			if ok != c.ok || got != c.want {
				t.Fatalf("NormalizeEmail(%q) = %q, %v; want %q, %v", c.in, got, ok, c.want, c.ok)
			}
		})
	}
}

func TestEmailSyncAllowed(t *testing.T) {
	cases := map[string]bool{"gitlab": true, "": false, "email": false, "saml": false, "ldap": false, "GitLab": false}
	for auth, want := range cases {
		if got := EmailSyncAllowed(auth); got != want {
			t.Fatalf("EmailSyncAllowed(%q) = %v, want %v", auth, got, want)
		}
	}
}

func TestSplitName(t *testing.T) {
	// Must match the GitLab provider's split (oauthproviders/gitlab), so a
	// panel sign-in and an OAuth sign-in store the same first and last name.
	cases := []struct{ in, first, last string }{
		{"", "", ""},
		{"Cher", "Cher", ""},
		{"Josh Hermsmeyer", "Josh", "Hermsmeyer"},
		{"Mary Jo Smith", "Mary", "Jo Smith"},
	}
	for _, c := range cases {
		f, l := SplitName(c.in)
		if f != c.first || l != c.last {
			t.Fatalf("SplitName(%q) = %q, %q; want %q, %q", c.in, f, l, c.first, c.last)
		}
	}
}

func TestPanelProfileChanges(t *testing.T) {
	cur := Profile{Email: "old@example.com", FirstName: "Josh", LastName: "H"}
	cases := []struct {
		name                   string
		claimEmail, claimName  string
		want                   Profile
		emailChanged, nameChgd bool
	}{
		{"unchanged", "old@example.com", "Josh H", cur, false, false},
		{"email case only", "OLD@Example.com", "Josh H", cur, false, false},
		{"new email", "new@example.com", "Josh H",
			Profile{Email: "new@example.com", FirstName: "Josh", LastName: "H"}, true, false},
		{"invalid email kept", "not-an-email", "Josh H", cur, false, false},
		{"empty email kept", "", "Josh H", cur, false, false},
		{"new name", "old@example.com", "Joshua Hermsmeyer",
			Profile{Email: "old@example.com", FirstName: "Joshua", LastName: "Hermsmeyer"}, false, true},
		{"both", "New@example.com", "Mary Jo Smith",
			Profile{Email: "new@example.com", FirstName: "Mary", LastName: "Jo Smith"}, true, true},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got, emailChanged, nameChanged := PanelProfileChanges(cur, c.claimEmail, c.claimName)
			if got != c.want || emailChanged != c.emailChanged || nameChanged != c.nameChgd {
				t.Fatalf("got %+v email=%v name=%v; want %+v email=%v name=%v",
					got, emailChanged, nameChanged, c.want, c.emailChanged, c.nameChgd)
			}
		})
	}
}
