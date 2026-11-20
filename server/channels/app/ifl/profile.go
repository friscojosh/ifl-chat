package ifl

import (
	"strings"

	"github.com/mattermost/mattermost/server/public/model"
)

// Profile is the part of a chat account that iflgm.com owns.
type Profile struct {
	Email     string
	FirstName string
	LastName  string
}

// NormalizeEmail lowercases and trims a site email and says whether it is a
// valid chat email (a plain address, at most model.UserEmailMaxLength long).
func NormalizeEmail(email string) (string, bool) {
	e := strings.ToLower(strings.TrimSpace(email))
	if e == "" || len(e) > model.UserEmailMaxLength || !model.IsValidEmail(e) {
		return "", false
	}
	return e, true
}

// EmailSyncAllowed says whether the site may set an account's email: only
// accounts signed in through iflgm.com (the GitLab-shaped provider).
func EmailSyncAllowed(authService string) bool {
	return authService == model.UserAuthServiceGitlab
}

// SplitName splits a full name the way the GitLab provider does
// (oauthproviders/gitlab userFromGitLabUser).
func SplitName(name string) (first, last string) {
	parts := strings.Split(name, " ")
	if len(parts) >= 2 {
		return parts[0], strings.Join(parts[1:], " ")
	}
	return name, ""
}

// PanelProfileChanges applies a panel token's email and name to an existing
// account's profile, as LoginByOAuth's UpdateOAuthUserAttrs does at an OAuth
// sign-in. An empty or invalid claim email leaves the email alone. The caller
// must still skip the email when another account holds it.
func PanelProfileChanges(cur Profile, claimEmail, claimName string) (next Profile, emailChanged, nameChanged bool) {
	next = cur
	if e, ok := NormalizeEmail(claimEmail); ok && e != strings.ToLower(cur.Email) {
		next.Email = e
		emailChanged = true
	}
	if first, last := SplitName(claimName); first != cur.FirstName || last != cur.LastName {
		next.FirstName, next.LastName = first, last
		nameChanged = true
	}
	return next, emailChanged, nameChanged
}
