// IFL: league chat fork (IFL Chat apps plan). The team chip: which league
// team each GM runs, from iflgm.com, mapped onto chat accounts.
package ifl

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"regexp"
	"strconv"
)

// BadgeTeam is one team's chip: abbreviation, full name, conference, the
// colour of the text chip, and the logo's revision (part of its URL).
type BadgeTeam struct {
	Abbr       string `json:"abbr"`
	Name       string `json:"name"`
	Conference string `json:"conference"`
	Color      string `json:"color"`
	LogoRev    string `json:"logo_rev"`
}

// BadgeMember is one chat-eligible GM on the site.
type BadgeMember struct {
	SiteUserID int64  `json:"site_user_id"`
	Abbr       string `json:"abbr"`
}

// SiteBadges is the site's GET /internal/chat/team-badges.
type SiteBadges struct {
	Version string        `json:"version"`
	Teams   []BadgeTeam   `json:"teams"`
	Members []BadgeMember `json:"members"`
}

// Badges is what chat clients get: teams by abbreviation, and chat user id
// to abbreviation. Version changes whenever either does.
type Badges struct {
	Version string               `json:"version"`
	Teams   map[string]BadgeTeam `json:"teams"`
	Users   map[string]string    `json:"users"`
}

// ChatAccount is the part of a chat account the mapping needs. AuthData is
// the site user id of an account that signs in through iflgm.com; only the
// server and system admins can set it.
type ChatAccount struct {
	ID       string
	AuthData string
	Active   bool
	IsBot    bool
}

var (
	badgeAbbrPattern  = regexp.MustCompile(`^[A-Z]{2,3}$`)
	badgeColorPattern = regexp.MustCompile(`^#[0-9A-Fa-f]{6}$`)
	badgeRevPattern   = regexp.MustCompile(`^[0-9a-f]{0,64}$`)
)

const maxBadgeName = 100

// ValidBadgeAbbr: two or three capital letters, as the site's team keys.
func ValidBadgeAbbr(abbr string) bool { return badgeAbbrPattern.MatchString(abbr) }

// BuildBadges keeps the site's well-formed teams, and gives a chip to each
// active, non-bot chat account whose AuthData is a listed member's site id.
func BuildBadges(site *SiteBadges, accounts []ChatAccount) Badges {
	b := Badges{Teams: map[string]BadgeTeam{}, Users: map[string]string{}}
	if site != nil {
		for _, t := range site.Teams {
			if !badgeAbbrPattern.MatchString(t.Abbr) || !badgeColorPattern.MatchString(t.Color) ||
				!badgeRevPattern.MatchString(t.LogoRev) || t.Name == "" || len(t.Name) > maxBadgeName ||
				len(t.Conference) > maxBadgeName {
				continue
			}
			b.Teams[t.Abbr] = t
		}
		bySiteID := map[string]string{}
		for _, m := range site.Members {
			if _, ok := b.Teams[m.Abbr]; ok && m.SiteUserID > 0 {
				bySiteID[strconv.FormatInt(m.SiteUserID, 10)] = m.Abbr
			}
		}
		for _, a := range accounts {
			if !a.Active || a.IsBot {
				continue
			}
			if abbr, ok := bySiteID[a.AuthData]; ok {
				b.Users[a.ID] = abbr
			}
		}
	}
	// encoding/json writes map keys in sorted order, so equal content gives
	// an equal version.
	raw, _ := json.Marshal(struct {
		Teams map[string]BadgeTeam `json:"teams"`
		Users map[string]string    `json:"users"`
	}{b.Teams, b.Users})
	sum := sha256.Sum256(raw)
	b.Version = hex.EncodeToString(sum[:16])
	return b
}

// EmptyBadges is the answer before the first good refresh: no chips.
func EmptyBadges() Badges { return BuildBadges(nil, nil) }
