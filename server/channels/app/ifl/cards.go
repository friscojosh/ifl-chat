// IFL: league chat fork (app cards). The score and news cards members share
// from iflgm.com: chat's clients draw them from the site's own copy, fetched
// here from the site's private listener with the internal secret.
package ifl

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"regexp"
)

// ErrNoCard: the site has no such game or story.
var ErrNoCard = errors.New("iflgm.com has no such card")

var (
	matchupIDPattern  = regexp.MustCompile(`^[0-9]{1,12}$`)
	storyIDPattern    = regexp.MustCompile(`^[^\s/?#]{1,40}$`)
	viewerSitePattern = regexp.MustCompile(`^[0-9]{1,12}$`)
)

// ValidMatchupID: the id a score card carries (props.ifl_score.id).
func ValidMatchupID(id string) bool { return matchupIDPattern.MatchString(id) }

// ValidStoryID: the id a news card carries (props.ifl_news.id).
func ValidStoryID(id string) bool { return storyIDPattern.MatchString(id) }

const maxCardBody = 256 << 10

// ScoreCard is the site's GET /internal/chat/cards/score/<id>, unchanged:
// {week, matchup}. It must be a JSON object.
func (s *SiteClient) ScoreCard(ctx context.Context, matchupID string) ([]byte, error) {
	if !ValidMatchupID(matchupID) {
		return nil, ErrNoCard
	}
	return s.card(ctx, "/internal/chat/cards/score/"+matchupID)
}

// NewsCard is the site's GET /internal/chat/cards/news/<id>, unchanged:
// {item}. viewer is the member's iflgm.com id (their team's owner chip is
// marked mine); empty or malformed, it is left out.
func (s *SiteClient) NewsCard(ctx context.Context, storyID, viewer string) ([]byte, error) {
	if !ValidStoryID(storyID) {
		return nil, ErrNoCard
	}
	path := "/internal/chat/cards/news/" + url.PathEscape(storyID)
	if viewerSitePattern.MatchString(viewer) {
		path += "?viewer=" + viewer
	}
	return s.card(ctx, path)
}

func (s *SiteClient) card(ctx context.Context, path string) ([]byte, error) {
	raw, err := s.get(ctx, path, maxCardBody)
	if errors.Is(err, errSiteNotFound) {
		return nil, ErrNoCard
	}
	if err != nil {
		return nil, err
	}
	var obj map[string]json.RawMessage
	if err := json.Unmarshal(raw, &obj); err != nil || obj == nil {
		return nil, fmt.Errorf("iflgm.com sent an unreadable card")
	}
	return bytes.TrimSpace(raw), nil
}
