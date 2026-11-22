// Copyright (c) 2015-present Mattermost, Inc. All Rights Reserved.
// See LICENSE.txt for license information.

// IFL: new file. The desktop sign-in hand-off goes to the IFL Chat desktop
// app's scheme (friscojosh/ifl-chat-desktop), so a stock Mattermost Desktop
// on the same machine is never opened.

export const IFL_DESKTOP_PROTOCOL = 'iflchat';

export function iflDesktopHandoffURL(href: string): string {
    const url = new URL(href);
    const protocol = url.searchParams.get('isDesktopDev') ? `${IFL_DESKTOP_PROTOCOL}-dev` : IFL_DESKTOP_PROTOCOL;
    return url.toString().replace(url.protocol, `${protocol}:`);
}
