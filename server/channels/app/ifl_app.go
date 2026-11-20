// IFL: league chat fork (plan 4). App-level glue for server/channels/app/ifl.
package app

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
	"time"

	"github.com/mattermost/mattermost/server/public/model"
	"github.com/mattermost/mattermost/server/public/shared/mlog"
	"github.com/mattermost/mattermost/server/public/shared/request"
	"github.com/mattermost/mattermost/server/v8/channels/app/ifl"
)

const iflPanelJTITokenType = "ifl_panel_jti"

func iflConfig() ifl.Config { return ifl.ConfigFromEnv() }

// IFLProvision puts a GitLab-authenticated member in the IFL team and its
// default channels (idempotent).
func (a *App) IFLProvision(rctx request.CTX, user *model.User) {
	if user.AuthService != model.ServiceGitlab {
		return
	}
	cfg := iflConfig()
	if cfg.TeamName == "" {
		rctx.Logger().Error("IFL: IFL_TEAM_NAME is not set; member not added to the league team", mlog.String("user_id", user.Id))
		return
	}
	team, appErr := a.GetTeamByName(cfg.TeamName)
	if appErr != nil {
		rctx.Logger().Error("IFL: team missing", mlog.String("team", cfg.TeamName), mlog.Err(appErr))
		return
	}
	if appErr := a.AddUserToTeamByTeamId(rctx, team.Id, user); appErr != nil {
		rctx.Logger().Warn("IFL: add to team", mlog.String("user_id", user.Id), mlog.Err(appErr))
	}
}

// IFLReactivateIfNeeded reactivates a deactivated GitLab account at sign-in:
// the site has just vouched for the member's eligibility.
func (a *App) IFLReactivateIfNeeded(rctx request.CTX, user *model.User) (*model.User, *model.AppError) {
	if user.AuthService != model.ServiceGitlab || user.DeleteAt == 0 {
		return user, nil
	}
	return a.UpdateActive(rctx, user, true)
}

// IFLPanelSession exchanges the site's two-minute panel token for a 24-hour
// session (spec §3, Panel session exchange).
func (a *App) IFLPanelSession(rctx request.CTX, token string) (*model.Session, *model.AppError) {
	cfg := iflConfig()
	if !cfg.PanelEnabled() {
		rctx.Logger().Error("IFL: panel session requested but IFL_SESSION_SECRET is missing or shorter than 32 characters")
		return nil, model.NewAppError("IFLPanelSession", "ifl.panel.disabled", nil, "", http.StatusServiceUnavailable)
	}
	claims, err := ifl.VerifyPanelToken(token, cfg.SessionSecret, time.Now())
	if err != nil {
		return nil, model.NewAppError("IFLPanelSession", "ifl.panel.invalid", nil, err.Error(), http.StatusUnauthorized)
	}
	// Single use: the token store's primary key is 64 characters exactly, so
	// store the jti's SHA-256 (hex) — the 32-hex jti itself fails IsValid.
	sum := sha256.Sum256([]byte(claims.JTI))
	if saveErr := a.Srv().Store().Token().Save(&model.Token{Token: hex.EncodeToString(sum[:]), CreateAt: model.GetMillis(), Type: iflPanelJTITokenType}); saveErr != nil {
		return nil, model.NewAppError("IFLPanelSession", "ifl.panel.replayed", nil, "", http.StatusUnauthorized)
	}

	authData := strconv.FormatInt(claims.SiteID, 10)
	user, appErr := a.GetUserByAuth(&authData, model.ServiceGitlab)
	if appErr != nil {
		if appErr.Id != MissingAuthAccountError {
			return nil, appErr
		}
		data, _ := json.Marshal(map[string]any{"id": claims.SiteID, "username": claims.Username,
			"email": claims.Email, "name": claims.Name})
		if user, appErr = a.CreateOAuthUser(rctx, model.ServiceGitlab, bytes.NewReader(data), "", "", nil); appErr != nil {
			return nil, appErr
		}
	}
	if user.IsBot {
		return nil, model.NewAppError("IFLPanelSession", "ifl.panel.bot", nil, "", http.StatusForbidden)
	}
	if user, appErr = a.IFLReactivateIfNeeded(rctx, user); appErr != nil {
		return nil, appErr
	}
	a.IFLProvision(rctx, user)

	session := &model.Session{
		UserId:    user.Id,
		Roles:     user.GetRawRoles(),
		ExpiresAt: model.GetMillis() + int64((24*time.Hour)/time.Millisecond),
		Props:     model.StringMap{"ifl_panel": "true", model.SessionPropPlatform: "iflgm.com panel"},
	}
	session.GenerateCSRF() // as every upstream login does; guards cookie use of this session
	return a.CreateSession(rctx, session)
}

// IFLMirrorActiveChange asks the site first when an admin deactivates or
// reactivates a site-linked member (spec §3, Started in chat). It fails
// closed: if the site callback is not configured, the change is refused.
func (a *App) IFLMirrorActiveChange(rctx request.CTX, target *model.User, active, permanentDelete bool, actorUsername string) *model.AppError {
	cfg := iflConfig()
	if !ifl.ShouldMirror(target.AuthService, actorUsername, cfg.ServiceUsername, false) {
		return nil
	}
	if target.AuthData == nil || *target.AuthData == "" {
		return nil
	}
	if _, err := strconv.ParseInt(*target.AuthData, 10, 64); err != nil {
		return nil
	}
	if !cfg.CallbackEnabled() {
		// Suspension below returns an error, so the change is refused.
		rctx.Logger().Error("IFL: site callback not configured (IFL_SITE_INTERNAL_URL / IFL_INTERNAL_SECRET); refusing active-state change of a site-linked member",
			mlog.String("user_id", target.Id))
	}
	action := "suspend"
	if active {
		action = "restore"
	}
	res, err := ifl.NewSiteClient(cfg).Suspension(rctx.Context(), *target.AuthData, action, actorUsername)
	if !active && !permanentDelete && errors.Is(err, ifl.ErrNoSiteAccount) {
		// The site account is gone (deleted): there is nothing to suspend, so a
		// reversible deactivation may proceed. A permanent delete still fails
		// closed, and a restore always needs a site account.
		rctx.Logger().Warn("IFL: site has no account for this member; allowing chat deactivation",
			mlog.String("user_id", target.Id), mlog.String("site_id", *target.AuthData),
			mlog.String("actor", actorUsername))
		return nil
	}
	if err != nil {
		return model.NewAppError("IFLMirrorActiveChange", "ifl.suspension.site_refused", map[string]any{"Reason": err.Error()}, "", http.StatusConflict)
	}
	if active && !res.Eligible {
		reason := "not eligible"
		if res.Reason != nil {
			reason = *res.Reason
		}
		return model.NewAppError("IFLMirrorActiveChange", "ifl.suspension.not_eligible", map[string]any{"Reason": reason}, "", http.StatusConflict)
	}
	return nil
}
