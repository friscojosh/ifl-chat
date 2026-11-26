// IFL: league chat fork (app cards). The score and news cards members share
// from iflgm.com, read from the site for chat's clients, with a short
// in-memory cache: concurrent misses for the same card share one call.
package app

import (
	"context"
	"errors"
	"net/http"
	"sync"
	"time"

	"github.com/mattermost/mattermost/server/public/model"
	"github.com/mattermost/mattermost/server/public/shared/request"
	"github.com/mattermost/mattermost/server/v8/channels/app/ifl"
)

const (
	// IFLScoreCardMaxAge is how long a game's score is reused (and the
	// route's Cache-Control max-age): a live card refetches every minute.
	IFLScoreCardMaxAge = 15 * time.Second
	// iflNewsCardMaxAge: a story's text does not change; its owners can.
	iflNewsCardMaxAge = time.Minute
	iflCardTimeout    = 10 * time.Second
	// Past this many cached cards, expired ones are dropped on the next miss.
	iflCardPrune = 2000
)

type iflCardEntry struct {
	done chan struct{} // closed when the call ends
	body []byte
	err  *model.AppError
	at   time.Time
}

type iflCardCache struct {
	mu      sync.Mutex
	entries map[string]*iflCardEntry
}

// One cache per server: api4 tests run many servers in one process.
var iflCardCaches sync.Map

func (a *App) iflCardCache() *iflCardCache {
	c, _ := iflCardCaches.LoadOrStore(a.Srv(), &iflCardCache{entries: map[string]*iflCardEntry{}})
	return c.(*iflCardCache)
}

// get answers from the cache when the card is younger than maxAge, else
// calls load once for everyone asking. Failures are not kept.
func (c *iflCardCache) get(rctx request.CTX, key string, maxAge time.Duration, load func(context.Context) ([]byte, *model.AppError)) ([]byte, *model.AppError) {
	c.mu.Lock()
	if e, ok := c.entries[key]; ok {
		select {
		case <-e.done:
			if e.err == nil && time.Since(e.at) < maxAge {
				c.mu.Unlock()
				return e.body, nil
			}
		default:
			c.mu.Unlock()
			select {
			case <-e.done:
				return e.body, e.err
			case <-rctx.Context().Done():
				return nil, iflCardsUnavailable(rctx.Context().Err())
			}
		}
	}
	if len(c.entries) >= iflCardPrune {
		for k, e := range c.entries {
			select {
			case <-e.done:
				if time.Since(e.at) >= maxAge {
					delete(c.entries, k)
				}
			default:
			}
		}
	}
	e := &iflCardEntry{done: make(chan struct{})}
	c.entries[key] = e
	c.mu.Unlock()

	// Not the request's context: others may be waiting on this call.
	ctx, cancel := context.WithTimeout(context.Background(), iflCardTimeout)
	defer cancel()
	body, appErr := load(ctx)

	c.mu.Lock()
	e.body, e.err, e.at = body, appErr, time.Now()
	if appErr != nil && c.entries[key] == e {
		delete(c.entries, key)
	}
	close(e.done)
	c.mu.Unlock()
	return body, appErr
}

func iflCardsUnavailable(err error) *model.AppError {
	return model.NewAppError("IFLCards", "ifl.cards.unavailable", nil, "", http.StatusBadGateway).Wrap(err)
}

func iflCardError(err error) *model.AppError {
	if errors.Is(err, ifl.ErrNoCard) {
		return model.NewAppError("IFLCards", "ifl.cards.not_found", nil, "", http.StatusNotFound)
	}
	return iflCardsUnavailable(err)
}

// IFLScoreCard is the site's score card for a game, unchanged:
// {week, matchup}. 404 ifl.cards.not_found for no such game, 502
// ifl.cards.unavailable when the site cannot answer.
func (a *App) IFLScoreCard(rctx request.CTX, matchupID string) ([]byte, *model.AppError) {
	if !ifl.ValidMatchupID(matchupID) {
		return nil, iflCardError(ifl.ErrNoCard)
	}
	return a.iflCardCache().get(rctx, "score/"+matchupID, IFLScoreCardMaxAge, func(ctx context.Context) ([]byte, *model.AppError) {
		cfg := iflConfig()
		if !cfg.CallbackEnabled() {
			return nil, iflCardsUnavailable(errors.New("IFL_SITE_INTERNAL_URL / IFL_INTERNAL_SECRET not set"))
		}
		body, err := ifl.NewSiteClient(cfg).ScoreCard(ctx, matchupID)
		if err != nil {
			return nil, iflCardError(err)
		}
		return body, nil
	})
}

// IFLNewsCard is the site's news card for a story, unchanged: {item}, with
// the viewer's own team marked among the owners when the session user signs
// in through iflgm.com. Same errors as IFLScoreCard.
func (a *App) IFLNewsCard(rctx request.CTX, storyID, userID string) ([]byte, *model.AppError) {
	if !ifl.ValidStoryID(storyID) {
		return nil, iflCardError(ifl.ErrNoCard)
	}
	viewer := ""
	if user, appErr := a.GetUser(rctx, userID); appErr == nil && user.AuthService == model.UserAuthServiceGitlab && user.AuthData != nil {
		viewer = *user.AuthData
	}
	return a.iflCardCache().get(rctx, "news/"+viewer+"/"+storyID, iflNewsCardMaxAge, func(ctx context.Context) ([]byte, *model.AppError) {
		cfg := iflConfig()
		if !cfg.CallbackEnabled() {
			return nil, iflCardsUnavailable(errors.New("IFL_SITE_INTERNAL_URL / IFL_INTERNAL_SECRET not set"))
		}
		body, err := ifl.NewSiteClient(cfg).NewsCard(ctx, storyID, viewer)
		if err != nil {
			return nil, iflCardError(err)
		}
		return body, nil
	})
}
