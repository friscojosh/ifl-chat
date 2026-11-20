package ifl

import "testing"

func TestShouldMirror(t *testing.T) {
	cases := []struct {
		name                 string
		auth, actor, service string
		self, want           bool
	}{
		{"non-gitlab target", "", "admin", "relay", false, false},
		{"saml target", "saml", "admin", "relay", false, false},
		{"self change", "gitlab", "admin", "relay", true, false},
		{"actor is service account", "gitlab", "relay", "relay", false, false},
		{"human admin", "gitlab", "admin", "relay", false, true},
		{"local mode", "gitlab", "mmctl-local", "relay", false, true},
		{"no service username configured", "gitlab", "admin", "", false, true},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := ShouldMirror(c.auth, c.actor, c.service, c.self); got != c.want {
				t.Fatalf("got %v want %v", got, c.want)
			}
		})
	}
}
