// Package ifl holds the IFL Chat fork's own logic (league chat spec §2–§3).
// It imports nothing from the app layer so it can be tested on its own.
package ifl

import (
	"os"
	"strings"
)

type Config struct {
	SessionSecret   string // IFL_SESSION_SECRET: the site's CHAT_SESSION_SECRET
	SiteInternalURL string // IFL_SITE_INTERNAL_URL: http://10.98.0.1:8081
	InternalSecret  string // IFL_INTERNAL_SECRET: the site's CHAT_INTERNAL_SECRET
	TeamName        string // IFL_TEAM_NAME: team every member joins
	ServiceUsername string // IFL_SERVICE_USERNAME: the relay's admin account
}

const minSecretLength = 32

func ConfigFromEnv() Config {
	return Config{
		SessionSecret:   os.Getenv("IFL_SESSION_SECRET"),
		SiteInternalURL: strings.TrimRight(os.Getenv("IFL_SITE_INTERNAL_URL"), "/"),
		InternalSecret:  os.Getenv("IFL_INTERNAL_SECRET"),
		TeamName:        os.Getenv("IFL_TEAM_NAME"),
		ServiceUsername: os.Getenv("IFL_SERVICE_USERNAME"),
	}
}

func (c Config) PanelEnabled() bool { return len(c.SessionSecret) >= minSecretLength }
func (c Config) CallbackEnabled() bool {
	return c.SiteInternalURL != "" && len(c.InternalSecret) >= minSecretLength
}
