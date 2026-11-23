package ifl

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
)

// Trading from chat (league chat spec §7, plan 9). iflgm.com owns trades;
// chat forwards the /trade command and signs the requests that card
// buttons and trade dialogs send to the site's private listener.
const (
	TradeCommandPath = "/internal/chat/trade/command"
	TradeActionPath  = "/internal/chat/trade/action"
	TradeDialogPath  = "/internal/chat/trade/dialog"
	SecretHeader     = "X-IFL-Chat-Secret"
	SiteUserHeader   = "X-IFL-Site-User"
)

// IsTradeCallback reports whether u is one of the site's trade callbacks:
// the scheme and host:port of IFL_SITE_INTERNAL_URL and exactly the action
// or dialog path, with no query, fragment or user info. Only these requests
// get the internal secret, so a member's own button pointing anywhere else
// on the private listener (the suspension callback, say) never carries it.
func (c Config) IsTradeCallback(u *url.URL) bool {
	if u == nil || !c.CallbackEnabled() {
		return false
	}
	base, err := url.Parse(c.SiteInternalURL)
	if err != nil || base.Host == "" {
		return false
	}
	if u.Scheme != base.Scheme || u.Host != base.Host || u.User != nil || u.RawQuery != "" || u.Fragment != "" || u.Opaque != "" {
		return false
	}
	path := u.EscapedPath()
	return path == base.EscapedPath()+TradeActionPath || path == base.EscapedPath()+TradeDialogPath
}

// TradeCommandResult is the site's answer to /trade: text to show the
// member (empty when the site opened a dialog instead).
type TradeCommandResult struct {
	Text string `json:"text"`
}

// TradeCommand forwards /trade [team] to the site with the member's site
// id. The site opens a dialog with triggerID or answers with text. In a
// direct message, dmPartnerSiteID is the other member's site id (the site
// pre-selects their team in "Trade with"); empty otherwise.
func (s *SiteClient) TradeCommand(ctx context.Context, siteID, triggerID, channelID, text, dmPartnerSiteID string) (*TradeCommandResult, error) {
	if !s.cfg.CallbackEnabled() {
		return nil, fmt.Errorf("site callback is not configured")
	}
	if !siteIDPattern.MatchString(siteID) {
		return nil, fmt.Errorf("invalid site user id %q", siteID)
	}
	fields := map[string]string{"trigger_id": triggerID, "channel_id": channelID, "text": text}
	if siteIDPattern.MatchString(dmPartnerSiteID) {
		fields["dm_partner_site_id"] = dmPartnerSiteID
	}
	body, _ := json.Marshal(fields)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, s.cfg.SiteInternalURL+TradeCommandPath, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set(SecretHeader, s.cfg.InternalSecret)
	req.Header.Set(SiteUserHeader, siteID)
	resp, err := s.http.Do(req)
	if err != nil {
		return nil, fmt.Errorf("iflgm.com unreachable: %w", err)
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 64<<10))
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("iflgm.com refused /trade: %s", resp.Status)
	}
	var r TradeCommandResult
	if err := json.Unmarshal(raw, &r); err != nil {
		return nil, fmt.Errorf("iflgm.com sent an unreadable answer: %w", err)
	}
	return &r, nil
}
