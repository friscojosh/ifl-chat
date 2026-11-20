package ifl

// ShouldMirror says whether a chat-side active-state change must first be
// agreed by the site (spec §3, Started in chat).
func ShouldMirror(targetAuthService, actorUsername, serviceUsername string, selfChange bool) bool {
	if targetAuthService != "gitlab" || selfChange {
		return false
	}
	// The relay's own deactivations follow site eligibility; they are not bans.
	return serviceUsername == "" || actorUsername != serviceUsername
}
