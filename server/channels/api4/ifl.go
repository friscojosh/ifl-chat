// IFL: league chat fork (plan 4).
package api4

import (
	"encoding/json"
	"net/http"

	"github.com/mattermost/mattermost/server/public/model"
	"github.com/mattermost/mattermost/server/v8/channels/app/ifl"
)

func (api *API) InitIFL() {
	api.BaseRoutes.APIRoot.Handle("/ifl/session", api.APIHandler(iflPanelSession)).Methods(http.MethodPost)
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
	if appErr := c.App.IFLMirrorActiveChange(c.AppContext, target, active, actor); appErr != nil {
		c.Err = appErr
		return false
	}
	return true
}
