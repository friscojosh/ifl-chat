package ifl

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func siteBadges() *SiteBadges {
	return &SiteBadges{
		Version: "site-v1",
		Teams: []BadgeTeam{
			{Abbr: "LAC", Name: "Los Angeles Chargers", Conference: "AFC", Color: "#007BC7", LogoRev: "aa11"},
			{Abbr: "MIA", Name: "Miami Dolphins", Conference: "AFC", Color: "#008E97", LogoRev: "bb22"},
			{Abbr: "bad", Name: "Lower case", Conference: "AFC", Color: "#000000"},
			{Abbr: "NYG", Name: "No colour", Conference: "NFC", Color: "red"},
		},
		Members: []BadgeMember{
			{SiteUserID: 1, Abbr: "LAC"},
			{SiteUserID: 2, Abbr: "MIA"},
			{SiteUserID: 3, Abbr: "LAC"},
			{SiteUserID: 4, Abbr: "NYG"},
			{SiteUserID: 5, Abbr: "LAC"},
		},
	}
}

func TestBuildBadgesMapsLinkedActiveAccounts(t *testing.T) {
	b := BuildBadges(siteBadges(), []ChatAccount{
		{ID: "u1", AuthData: "1", Active: true},
		{ID: "u2", AuthData: "2", Active: true},
		{ID: "u3", AuthData: "3", Active: false}, // deactivated: no chip
		{ID: "u4", AuthData: "4", Active: true},  // team dropped (bad colour)
		{ID: "u5", AuthData: "5", Active: true, IsBot: true},
		{ID: "u6", AuthData: "6", Active: true}, // the site lists no team for them
	})
	if len(b.Teams) != 2 || b.Teams["LAC"].Name != "Los Angeles Chargers" || b.Teams["MIA"].LogoRev != "bb22" {
		t.Fatalf("teams %+v", b.Teams)
	}
	if len(b.Users) != 2 || b.Users["u1"] != "LAC" || b.Users["u2"] != "MIA" {
		t.Fatalf("users %+v", b.Users)
	}
	if len(b.Version) != 32 {
		t.Fatalf("version %q", b.Version)
	}
}

func TestBadgesVersionFollowsTheMapping(t *testing.T) {
	accounts := []ChatAccount{{ID: "u1", AuthData: "1", Active: true}}
	v1 := BuildBadges(siteBadges(), accounts).Version
	if BuildBadges(siteBadges(), accounts).Version != v1 {
		t.Fatal("version not stable")
	}
	moved := siteBadges()
	moved.Members[0].Abbr = "MIA"
	if BuildBadges(moved, accounts).Version == v1 {
		t.Fatal("a team change kept the version")
	}
	// A new GM linking their chat account changes the version though the site's did not.
	if BuildBadges(siteBadges(), append(accounts, ChatAccount{ID: "u2", AuthData: "2", Active: true})).Version == v1 {
		t.Fatal("a new link kept the version")
	}
	empty := EmptyBadges()
	if empty.Teams == nil || empty.Users == nil || empty.Version == "" {
		t.Fatalf("empty %+v", empty)
	}
}

func TestSiteTeamBadgesAndLogos(t *testing.T) {
	png := []byte("\x89PNG\r\n\x1a\nIFL")
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-IFL-Chat-Secret") != testInternalSecret || r.Method != http.MethodGet {
			w.WriteHeader(http.StatusUnauthorized)
			return
		}
		switch r.URL.Path + "?" + r.URL.RawQuery {
		case "/internal/chat/team-badges?":
			w.Write([]byte(`{"version":"v","teams":[{"abbr":"LAC","name":"Los Angeles Chargers","conference":"AFC","color":"#007BC7","logo_rev":"aa"}],"members":[{"site_user_id":7,"abbr":"LAC"}]}`))
		case "/internal/chat/team-logos/LAC.png?s=64":
			w.Write(png)
		case "/internal/chat/team-logos/MIA.png?s=64":
			w.Write([]byte("<html>not a png</html>"))
		case "/internal/chat/team-logos/BIG.png?s=64":
			w.Write(append(png, make([]byte, maxLogoBody)...))
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	defer srv.Close()
	c := clientFor(srv.URL)

	b, err := c.TeamBadges(context.Background())
	if err != nil || len(b.Teams) != 1 || b.Members[0].SiteUserID != 7 {
		t.Fatalf("badges %+v %v", b, err)
	}
	got, err := c.TeamLogo(context.Background(), "LAC", 64)
	if err != nil || string(got) != string(png) {
		t.Fatalf("logo %q %v", got, err)
	}
	if _, err := c.TeamLogo(context.Background(), "NYJ", 64); !errors.Is(err, ErrNoTeamLogo) {
		t.Fatalf("missing logo: %v", err)
	}
	for _, bad := range []string{"MIA", "BIG"} {
		if _, err := c.TeamLogo(context.Background(), bad, 64); err == nil || errors.Is(err, ErrNoTeamLogo) {
			t.Fatalf("%s: %v", bad, err)
		}
	}
	for _, abbr := range []string{"lac", "../X", "LACX"} {
		if _, err := c.TeamLogo(context.Background(), abbr, 64); !errors.Is(err, ErrNoTeamLogo) {
			t.Fatalf("%s: %v", abbr, err)
		}
	}
	if _, err := c.TeamLogo(context.Background(), "LAC", 32); !errors.Is(err, ErrNoTeamLogo) {
		t.Fatalf("size: %v", err)
	}
}

func TestSiteTeamBadgesNeedsConfig(t *testing.T) {
	_, err := NewSiteClient(Config{}).TeamBadges(context.Background())
	if err == nil || !strings.Contains(err.Error(), "not configured") {
		t.Fatalf("err %v", err)
	}
}
