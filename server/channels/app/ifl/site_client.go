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
// id (its own JSON "User not found", not a bare 404 from a misrouted proxy).
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
		}
		_ = json.Unmarshal(raw, &e)
		if resp.StatusCode == http.StatusNotFound && e.Error == "User not found" {
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
