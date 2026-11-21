// Copyright (c) 2015-present Mattermost, Inc. All Rights Reserved.
// See LICENSE.txt for license information.

// IFL: new file. Upstream features IFL Chat turns off in the signed-in app.
// Each hook that uses one is marked `// IFL:` (see IFL.md).

// Members are provisioned by iflgm.com (signing in there joins the league
// team), so chat never offers to invite people to the team.
export const IFL_TEAM_INVITES = false as boolean;

// No prompts to download Mattermost's desktop and mobile apps from mattermost.com.
export const IFL_APP_DOWNLOAD_PROMPTS = false as boolean;

// No links to Mattermost's documentation, academy or community in menus.
export const IFL_MATTERMOST_LINKS = false as boolean;

// No Enterprise trial, upgrade, licence-purchase or "contact sales" prompts:
// IFL Chat is a self-hosted Team Edition fork with nothing to buy.
export const IFL_UPSELLS = false as boolean;

// The team chip after GMs' names (IFL Chat apps plan): logos from iflgm.com.
export const IFL_TEAM_CHIPS = true as boolean;
