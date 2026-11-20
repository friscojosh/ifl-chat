// IFL: league chat fork. Tests for the IFL routes in ifl.go.
package api4

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"net/http"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/stretchr/testify/require"

	"github.com/mattermost/mattermost/server/public/model"
)

// iflGitlabUser creates a site-linked (GitLab) account with the given site id.
func iflGitlabUser(t *testing.T, th *TestHelper, siteID int64) *model.User {
	t.Helper()
	authData := strconv.FormatInt(siteID, 10)
	id := model.NewId()
	user, appErr := th.App.CreateUser(th.Context, &model.User{
		Email:       "ifl" + id + "@example.com",
		Username:    "ifl" + id[:10],
		AuthService: model.UserAuthServiceGitlab,
		AuthData:    &authData,
		FirstName:   "Old",
		LastName:    "Name",
	})
	require.Nil(t, appErr)
	return user
}

func iflPutEmail(c *model.Client4, userID, email string) (*http.Response, error) {
	return c.DoAPIPutJSON(context.Background(), "/ifl/users/"+userID+"/email", map[string]string{"email": email})
}

func TestIFLUpdateEmail(t *testing.T) {
	th := Setup(t).InitBasic(t)

	t.Run("non-admin gets 403", func(t *testing.T) {
		target := iflGitlabUser(t, th, 9001)
		resp, err := iflPutEmail(th.Client, target.Id, "new"+model.NewId()+"@example.com")
		require.Error(t, err)
		require.Equal(t, http.StatusForbidden, resp.StatusCode)
	})

	t.Run("non-gitlab target gets 400", func(t *testing.T) {
		resp, err := iflPutEmail(th.SystemAdminClient, th.BasicUser2.Id, "new"+model.NewId()+"@example.com")
		require.Error(t, err)
		require.Equal(t, http.StatusBadRequest, resp.StatusCode)
		CheckErrorID(t, err, "ifl.email.not_site_linked")
	})

	t.Run("address held by another account gets 409", func(t *testing.T) {
		target := iflGitlabUser(t, th, 9002)
		resp, err := iflPutEmail(th.SystemAdminClient, target.Id, th.BasicUser2.Email)
		require.Error(t, err)
		require.Equal(t, http.StatusConflict, resp.StatusCode)
		CheckErrorID(t, err, "ifl.email.conflict")
	})

	t.Run("changes the email and keeps roles and delete_at the cache has not seen", func(t *testing.T) {
		target := iflGitlabUser(t, th, 9003)
		// Prime the user cache with the active, plain-role copy.
		_, appErr := th.App.GetUser(th.Context, target.Id)
		require.Nil(t, appErr)

		// A ban and a role change written behind the cache's back.
		changed, err := th.App.Srv().Store().User().Get(th.Context, target.Id)
		require.NoError(t, err)
		changed.DeleteAt = model.GetMillis()
		changed.Roles = model.SystemUserRoleId + " " + model.SystemUserManagerRoleId
		_, err = th.App.Srv().Store().User().Update(th.Context, changed, true)
		require.NoError(t, err)

		newEmail := "New" + model.NewId() + "@Example.com"
		resp, err := iflPutEmail(th.SystemAdminClient, target.Id, newEmail)
		require.NoError(t, err)
		require.Equal(t, http.StatusOK, resp.StatusCode)

		th.App.InvalidateCacheForUser(target.Id)
		got, err := th.App.Srv().Store().User().Get(th.Context, target.Id)
		require.NoError(t, err)
		require.Equal(t, strings.ToLower(newEmail), got.Email)
		require.NotZero(t, got.DeleteAt, "deactivation must survive the email change")
		require.Equal(t, changed.DeleteAt, got.DeleteAt)
		require.Equal(t, changed.Roles, got.Roles, "roles must survive the email change")

		// Idempotent repeat.
		resp, err = iflPutEmail(th.SystemAdminClient, target.Id, got.Email)
		require.NoError(t, err)
		require.Equal(t, http.StatusOK, resp.StatusCode)
	})
}

func iflPanelToken(t *testing.T, secret string, siteID int64, username, email, name string) string {
	t.Helper()
	jti := make([]byte, 16)
	_, err := rand.Read(jti)
	require.NoError(t, err)
	now := time.Now()
	claims := jwt.MapClaims{
		"sub": strconv.FormatInt(siteID, 10), "aud": "ifl-chat", "iss": "iflgm.com",
		"iat": now.Unix(), "exp": now.Add(2 * time.Minute).Unix(), "jti": hex.EncodeToString(jti),
		"username": username, "email": email, "name": name,
	}
	signed, err := jwt.NewWithClaims(jwt.SigningMethodHS256, claims).SignedString([]byte(secret))
	require.NoError(t, err)
	return signed
}

func TestIFLPanelSessionProfileSync(t *testing.T) {
	secret := "0123456789abcdef0123456789abcdef-test"
	t.Setenv("IFL_SESSION_SECRET", secret)
	th := Setup(t).InitBasic(t)
	client := model.NewAPIv4Client(th.Client.URL)

	t.Run("syncs email and name", func(t *testing.T) {
		target := iflGitlabUser(t, th, 9101)
		newEmail := "panel" + model.NewId() + "@example.com"
		resp, err := client.DoAPIPostJSON(context.Background(), "/ifl/session",
			map[string]string{"token": iflPanelToken(t, secret, 9101, target.Username, newEmail, "Mary Jo Smith")})
		require.NoError(t, err)
		require.Equal(t, http.StatusOK, resp.StatusCode)

		got, err := th.App.Srv().Store().User().Get(th.Context, target.Id)
		require.NoError(t, err)
		require.Equal(t, newEmail, got.Email)
		require.Equal(t, "Mary", got.FirstName)
		require.Equal(t, "Jo Smith", got.LastName)
		require.Equal(t, target.Roles, got.Roles)
	})

	t.Run("skips an email another account holds", func(t *testing.T) {
		target := iflGitlabUser(t, th, 9102)
		resp, err := client.DoAPIPostJSON(context.Background(), "/ifl/session",
			map[string]string{"token": iflPanelToken(t, secret, 9102, target.Username, th.BasicUser2.Email, "New Name")})
		require.NoError(t, err)
		require.Equal(t, http.StatusOK, resp.StatusCode)

		got, err := th.App.Srv().Store().User().Get(th.Context, target.Id)
		require.NoError(t, err)
		require.Equal(t, target.Email, got.Email, "a taken email must be skipped")
		require.Equal(t, "New", got.FirstName, "the name still syncs")
		require.Equal(t, "Name", got.LastName)
	})
}
