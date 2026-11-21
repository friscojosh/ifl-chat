package ifl

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"regexp"
	"time"
)

// ErrNoSiteAccount means iflgm.com answered that it has no account with this
// id: a 404 carrying the site's code "no_site_account" (a bare 404 from a
// misrouted proxy, or any other body, stays a refusal).
var ErrNoSiteAccount = errors.New("iflgm.com has no account with this id")

type SuspensionResult struct {
	Suspended bool    `json:"suspended"`
	Eligible  bool    `json:"eligible"`
	Reason    *string `json:"reason"`
}

type SiteClient struct {
	cfg  Config
	http *http.Client
}

var siteIDPattern = regexp.MustCompile(`^[0-9]+$`)

func NewSiteClient(cfg Config) *SiteClient {
	return &SiteClient{cfg: cfg, http: &http.Client{
		Timeout: 5 * time.Second,
		// Never follow a redirect: it would forward the shared secret.
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
	}}
}

// Suspension asks the site to suspend or restore a member before chat
// changes their account (spec §3, Started in chat). Any failure is returned
// so the caller refuses the chat-side change.
func (s *SiteClient) Suspension(ctx context.Context, siteID string, action, actor string) (*SuspensionResult, error) {
	if action != "suspend" && action != "restore" {
		return nil, fmt.Errorf("unknown suspension action %q", action)
	}
	if !s.cfg.CallbackEnabled() {
		return nil, fmt.Errorf("site callback is not configured")
	}
	if !siteIDPattern.MatchString(siteID) {
		return nil, fmt.Errorf("invalid site user id %q", siteID)
	}
	body, _ := json.Marshal(map[string]string{"action": action, "actor": actor})
	url := fmt.Sprintf("%s/internal/chat/users/%s/suspension", s.cfg.SiteInternalURL, siteID)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-IFL-Chat-Secret", s.cfg.InternalSecret)
	resp, err := s.http.Do(req)
	if err != nil {
		return nil, fmt.Errorf("iflgm.com unreachable: %w", err)
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 64<<10))
	if resp.StatusCode != http.StatusOK {
		var e struct {
			Error string `json:"error"`
			Code  string `json:"code"`
		}
		_ = json.Unmarshal(raw, &e)
		if resp.StatusCode == http.StatusNotFound && e.Code == "no_site_account" {
			return nil, ErrNoSiteAccount
		}
		if e.Error == "" {
			e.Error = resp.Status
		}
		return nil, fmt.Errorf("iflgm.com refused: %s", e.Error)
	}
	var r SuspensionResult
	if err := json.Unmarshal(raw, &r); err != nil {
		return nil, fmt.Errorf("iflgm.com sent an unreadable answer: %w", err)
	}
	return &r, nil
}

// ErrNoTeamLogo: the site has no logo for this team and size (or the
// request was not a team key and size the site serves).
var ErrNoTeamLogo = errors.New("iflgm.com has no logo for this team")

var errSiteNotFound = errors.New("iflgm.com answered 404")

const (
	maxBadgeBody = 256 << 10
	maxLogoBody  = 256 << 10
)

var pngMagic = []byte("\x89PNG\r\n\x1a\n")

// get is a GET on the site's private listener with the internal secret.
func (s *SiteClient) get(ctx context.Context, path string, limit int) ([]byte, error) {
	if !s.cfg.CallbackEnabled() {
		return nil, fmt.Errorf("site callback is not configured")
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, s.cfg.SiteInternalURL+path, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("X-IFL-Chat-Secret", s.cfg.InternalSecret)
	resp, err := s.http.Do(req)
	if err != nil {
		return nil, fmt.Errorf("iflgm.com unreachable: %w", err)
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(io.LimitReader(resp.Body, int64(limit)+1))
	if err != nil {
		return nil, fmt.Errorf("iflgm.com answer unreadable: %w", err)
	}
	if resp.StatusCode == http.StatusNotFound {
		return nil, errSiteNotFound
	}
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("iflgm.com answered %s", resp.Status)
	}
	if len(raw) > limit {
		return nil, fmt.Errorf("iflgm.com answer larger than %d bytes", limit)
	}
	return raw, nil
}

// TeamBadges is every chat-eligible GM's team (IFL Chat apps plan).
func (s *SiteClient) TeamBadges(ctx context.Context) (*SiteBadges, error) {
	raw, err := s.get(ctx, "/internal/chat/team-badges", maxBadgeBody)
	if err != nil {
		return nil, err
	}
	var b SiteBadges
	if err := json.Unmarshal(raw, &b); err != nil {
		return nil, fmt.Errorf("iflgm.com sent unreadable team badges: %w", err)
	}
	return &b, nil
}

// TeamLogo is a team's square PNG logo, 64 or 128 px.
func (s *SiteClient) TeamLogo(ctx context.Context, abbr string, size int) ([]byte, error) {
	if !ValidBadgeAbbr(abbr) || (size != 64 && size != 128) {
		return nil, ErrNoTeamLogo
	}
	raw, err := s.get(ctx, fmt.Sprintf("/internal/chat/team-logos/%s.png?s=%d", abbr, size), maxLogoBody)
	if errors.Is(err, errSiteNotFound) {
		return nil, ErrNoTeamLogo
	}
	if err != nil {
		return nil, err
	}
	if !bytes.HasPrefix(raw, pngMagic) {
		return nil, fmt.Errorf("iflgm.com sent a team logo that is not a PNG")
	}
	return raw, nil
}
