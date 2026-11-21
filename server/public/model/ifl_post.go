// IFL: league chat fork (plan 8). Hook: post.go (SanitizeProps).
package model

// PostPropsIFLDeletedRoot marks a thread's first message that was deleted
// while it had replies (server/channels/app/ifl_moderation.go). Only the
// server sets it, writing the post directly; SanitizeProps strips it from
// every post a client, plugin or remote creates or updates, so nobody can
// mark a post of their own as deleted.
const PostPropsIFLDeletedRoot = "ifl_deleted_root"
