// IFL: league chat fork (plan 4).
package api4

import (
	"encoding/json"
	"net/http"

	"github.com/mattermost/mattermost/server/public/model"
	"github.com/mattermost/mattermost/server/public/shared/mlog"
	"github.com/mattermost/mattermost/server/v8/channels/app/ifl"
)

func (api *API) InitIFL() {
	api.BaseRoutes.APIRoot.Handle("/ifl/session", api.APIHandler(iflPanelSession)).Methods(http.MethodPost)
	api.BaseRoutes.APIRoot.Handle("/ifl/users/{user_id:[A-Za-z0-9]+}/email", api.APISessionRequired(iflUpdateEmail)).Methods(http.MethodPut)
	api.BaseRoutes.APIRoot.Handle("/ifl/websocket", api.APIHandlerTrustRequester(iflPanelWebSocket)).Methods(http.MethodGet)
}

// iflUpdateEmail sets a site-linked member's email (system admin only): the
// site's relay keeps chat's email in step with iflgm.com. PUT .../users/{id}/patch
// cannot, because chat keeps an OAuth user's old email on an untrusted update.
func iflUpdateEmail(c *Context, w http.ResponseWriter, r *http.Request) {
	c.RequireUserId()
	if c.Err != nil {
		return
	}

	// The audit record comes first, so a refused or malformed call is logged too.
	auditRec := c.MakeAuditRecord("iflUpdateEmail", model.AuditStatusFail)
	defer c.LogAuditRec(auditRec)
	model.AddEventParameterToAuditRec(auditRec, "user_id", c.Params.UserId)

	if !c.App.SessionHasPermissionTo(*c.AppContext.Session(), model.PermissionManageSystem) {
		c.SetPermissionError(model.PermissionManageSystem)
		return
	}
	var body struct {
		Email string `json:"email"`
	}
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 8<<10)).Decode(&body); err != nil || body.Email == "" {
		c.SetInvalidParam("email")
		return
	}
	model.AddEventParameterToAuditRec(auditRec, "email", body.Email)

	user, appErr := c.App.IFLUpdateEmail(c.AppContext, c.Params.UserId, body.Email)
	if appErr != nil {
		c.Err = appErr
		return
	}
	auditRec.Success()
	auditRec.AddEventResultState(user)
	auditRec.AddEventObjectType("user")

	c.App.SanitizeProfile(user, c.IsSystemAdmin())
	if err := json.NewEncoder(w).Encode(user); err != nil {
		c.Logger.Warn("Error while writing response", mlog.Err(err))
	}
}

func iflPanelSession(c *Context, w http.ResponseWriter, r *http.Request) {
	var body struct {
		Token string `json:"token"`
	}
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 8<<10)).Decode(&body); err != nil || body.Token == "" {
		c.SetInvalidParam("token")
		return
	}
	session, appErr := c.App.IFLPanelSession(c.AppContext, body.Token)
	if appErr != nil {
		c.Err = appErr
		return
	}
	w.Header().Set("Cache-Control", "no-store")
	_ = json.NewEncoder(w).Encode(map[string]any{
		"token": session.Token, "user_id": session.UserId, "expires_at": session.ExpiresAt,
	})
}

// iflMirrorFromAPI runs before an admin API call deactivates, reactivates or
// permanently deletes a member (spec §3, Started in chat). It returns false,
// with c.Err set, when the site refuses or cannot be reached; the caller must
// then stop.
func iflMirrorFromAPI(c *Context, target *model.User, active, permanentDelete bool) bool {
	session := c.AppContext.Session()
	if session.UserId == target.Id {
		return true // self-deactivation is not a ban
	}
	if !ifl.IsActiveStateChange(active, target.DeleteAt == 0, permanentDelete) {
		return true // no change in chat: never send the site a restore (or suspend) for it
	}
	actor := "mmctl-local" // local-mode sessions have no user
	if session.UserId != "" {
		actor = session.UserId // fallback if the acting user cannot be loaded
		if actingUser, err := c.App.GetUser(c.AppContext, session.UserId); err == nil {
			actor = actingUser.Username
		}
	}
	if appErr := c.App.IFLMirrorActiveChange(c.AppContext, target, active, permanentDelete, actor); appErr != nil {
		c.Err = appErr
		return false
	}
	return true
}

// iflPanelWebSocket is the iflgm.com panel's WebSocket (league chat plan 6).
// Browsers send chat.iflgm.com cookies with every WebSocket handshake
// (iflgm.com is the same site, so even SameSite cookies go), and the stock
// route binds that cookie's session before the client's authentication
// challenge is read; the router then ignores the challenge
// (app/platform/websocket_router.go:39-41). The panel authenticates only with
// its own Bearer session, so this route drops whatever session the handshake
// carried and lets the challenge decide. Same origin check, same connection
// handling; a resume (connection_id) never applies because the handshake has
// no user, so every connection starts fresh (hello at sequence 0) and the
// panel reconciles after every reconnect.
func iflPanelWebSocket(c *Context, w http.ResponseWriter, r *http.Request) {
	c.AppContext = c.AppContext.WithSession(&model.Session{})
	connectWebSocket(c, w, r)
}
