// IFL: league chat fork (IFL Chat apps plan). The team chip: an in-memory
// cache of every GM's team from iflgm.com, served to every client.
package app

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"sync"
	"time"

	"github.com/mattermost/mattermost/server/public/model"
	"github.com/mattermost/mattermost/server/public/shared/mlog"
	"github.com/mattermost/mattermost/server/public/shared/request"
	"github.com/mattermost/mattermost/server/v8/channels/app/ifl"
)

// IFLTeamBadgesChangedEvent tells every client to refetch the badges. The
// custom_ prefix (plugin events) means stock clients ignore it.
const IFLTeamBadgesChangedEvent model.WebsocketEventType = "custom_ifl_team_badges_changed"

const (
	iflBadgeMaxAge   = 10 * time.Minute
	iflBadgeRetryAge = time.Minute
	iflBadgeTimeout  = 10 * time.Second
)

type iflBadgeCache struct {
	refresh sync.Mutex // one refresh at a time

	mu        sync.Mutex // guards the fields below
	badges    ifl.Badges
	nextCheck time.Time // zero until the first refresh
	logos     map[string][]byte
	queued    bool // a background refresh is queued or running
}

// One cache per server: api4 tests run many servers in one process.
var iflBadgeCaches sync.Map

func (a *App) iflBadgeCache() *iflBadgeCache {
	c, _ := iflBadgeCaches.LoadOrStore(a.Srv(), &iflBadgeCache{badges: ifl.EmptyBadges(), logos: map[string][]byte{}})
	return c.(*iflBadgeCache)
}

// IFLTeamBadges returns the badges. The first call after start waits for a
// refresh; later calls answer at once and refresh in the background when
// the cache is due. Without a good refresh the answer has no chips, never
// an error.
func (a *App) IFLTeamBadges(rctx request.CTX) ifl.Badges {
	c := a.iflBadgeCache()
	c.mu.Lock()
	first, due := c.nextCheck.IsZero(), time.Now().After(c.nextCheck)
	c.mu.Unlock()
	if first {
		a.iflRefreshTeamBadges(rctx, true)
	} else if due {
		a.iflRefreshTeamBadgesLater()
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.badges
}

func (a *App) iflRefreshTeamBadgesLater() {
	c := a.iflBadgeCache()
	c.mu.Lock()
	if c.queued {
		c.mu.Unlock()
		return
	}
	c.queued = true
	c.mu.Unlock()
	a.Srv().Go(func() {
		defer func() {
			c.mu.Lock()
			c.queued = false
			c.mu.Unlock()
		}()
		a.IFLRefreshTeamBadges(request.EmptyContext(a.Log()))
	})
}

// iflNoteSignIn queues a refresh when a member who has no chip signs in, so
// a new GM gets theirs without waiting for the next check.
func (a *App) iflNoteSignIn(userID string) {
	c := a.iflBadgeCache()
	c.mu.Lock()
	_, has := c.badges.Users[userID]
	c.mu.Unlock()
	if !has {
		a.iflRefreshTeamBadgesLater()
	}
}

// IFLRefreshTeamBadges re-reads every GM's team now. A change is announced
// to every connection (IFLTeamBadgesChangedEvent). A failure keeps the last
// good badges, logs one warning and is tried again after a minute.
func (a *App) IFLRefreshTeamBadges(rctx request.CTX) (ifl.Badges, bool, *model.AppError) {
	return a.iflRefreshTeamBadges(rctx, false)
}

// iflRefreshTeamBadges refreshes; onlyFirst skips the refresh when another
// request finished the first one while this one waited, so members opening
// chat together at start cause one call to iflgm.com, not one each.
func (a *App) iflRefreshTeamBadges(rctx request.CTX, onlyFirst bool) (ifl.Badges, bool, *model.AppError) {
	c := a.iflBadgeCache()
	c.refresh.Lock()
	defer c.refresh.Unlock()
	if onlyFirst {
		c.mu.Lock()
		done, current := !c.nextCheck.IsZero(), c.badges
		c.mu.Unlock()
		if done {
			return current, false, nil
		}
	}

	next, err := a.iflLoadTeamBadges(rctx)
	if err != nil {
		rctx.Logger().Warn("IFL: team badges not refreshed; keeping the last good ones", mlog.Err(err))
		c.mu.Lock()
		c.nextCheck = time.Now().Add(iflBadgeRetryAge)
		current := c.badges
		c.mu.Unlock()
		return current, false, model.NewAppError("IFLRefreshTeamBadges", "ifl.team_badges.unavailable", nil, "", http.StatusBadGateway).Wrap(err)
	}
	c.mu.Lock()
	changed := next.Version != c.badges.Version
	if changed {
		c.logos = map[string][]byte{} // a logo_rev may have changed
	}
	c.badges = next
	c.nextCheck = time.Now().Add(iflBadgeMaxAge)
	c.mu.Unlock()
	if changed {
		ev := model.NewWebSocketEvent(IFLTeamBadgesChangedEvent, "", "", "", nil, "")
		ev.Add("version", next.Version)
		a.Publish(ev)
	}
	return next, changed, nil
}

func (a *App) iflLoadTeamBadges(rctx request.CTX) (ifl.Badges, error) {
	cfg := iflConfig()
	if !cfg.CallbackEnabled() {
		return ifl.Badges{}, errors.New("IFL_SITE_INTERNAL_URL / IFL_INTERNAL_SECRET not set")
	}
	ctx, cancel := context.WithTimeout(rctx.Context(), iflBadgeTimeout)
	defer cancel()
	site, err := ifl.NewSiteClient(cfg).TeamBadges(ctx)
	if err != nil {
		return ifl.Badges{}, err
	}
	users, err := a.Srv().Store().User().GetAllUsingAuthService(model.UserAuthServiceGitlab)
	if err != nil {
		return ifl.Badges{}, err
	}
	accounts := make([]ifl.ChatAccount, 0, len(users))
	for _, u := range users {
		authData := ""
		if u.AuthData != nil {
			authData = *u.AuthData
		}
		accounts = append(accounts, ifl.ChatAccount{ID: u.Id, AuthData: authData, Active: u.DeleteAt == 0, IsBot: u.IsBot})
	}
	return ifl.BuildBadges(site, accounts), nil
}

// IFLTeamLogo is a team's logo (64 or 128 px) for the public logo route;
// only teams in the current badges have one.
func (a *App) IFLTeamLogo(rctx request.CTX, abbr string, size int) ([]byte, *model.AppError) {
	notFound := model.NewAppError("IFLTeamLogo", "ifl.team_badges.no_logo", nil, "", http.StatusNotFound)
	if _, ok := a.IFLTeamBadges(rctx).Teams[abbr]; !ok || (size != 64 && size != 128) {
		return nil, notFound
	}
	c := a.iflBadgeCache()
	key := fmt.Sprintf("%s/%d", abbr, size)
	c.mu.Lock()
	png, ok := c.logos[key]
	c.mu.Unlock()
	if ok {
		return png, nil
	}
	ctx, cancel := context.WithTimeout(rctx.Context(), iflBadgeTimeout)
	defer cancel()
	png, err := ifl.NewSiteClient(iflConfig()).TeamLogo(ctx, abbr, size)
	if errors.Is(err, ifl.ErrNoTeamLogo) {
		return nil, notFound
	}
	if err != nil {
		return nil, model.NewAppError("IFLTeamLogo", "ifl.team_badges.unavailable", nil, "", http.StatusBadGateway).Wrap(err)
	}
	c.mu.Lock()
	c.logos[key] = png
	c.mu.Unlock()
	return png, nil
}
