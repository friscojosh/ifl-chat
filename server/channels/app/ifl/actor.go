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

// IsActiveStateChange says whether a chat-side request actually changes the
// member's state. A permanent delete always does, even of a deactivated
// member. Otherwise nothing is sent to the site when the requested state is
// already the current one: a "restore" for an already-active member would
// lift a suspension made on iflgm.com that the relay has not yet applied.
func IsActiveStateChange(requestedActive, currentlyActive, permanentDelete bool) bool {
	return permanentDelete || requestedActive != currentlyActive
}
