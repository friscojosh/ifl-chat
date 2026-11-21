// Copyright (c) 2015-present Mattermost, Inc. All Rights Reserved.
// See LICENSE.txt for license information.

// IFL: new file. The desktop sign-in hand-off opens the IFL Chat desktop app.

import {IFL_DESKTOP_PROTOCOL, iflDesktopHandoffURL} from './ifl_desktop';

describe('iflDesktopHandoffURL', () => {
    test('hands the server token to iflchat://', () => {
        expect(IFL_DESKTOP_PROTOCOL).toBe('iflchat');
        expect(iflDesktopHandoffURL('https://chat.iflgm.com/login/desktop?server_token=abc')).
            toBe('iflchat://chat.iflgm.com/login/desktop?server_token=abc');
    });

    test('dev builds of the desktop app get iflchat-dev://', () => {
        expect(iflDesktopHandoffURL('https://chat.iflgm.com/login/desktop?server_token=abc&isDesktopDev=true')).
            toBe('iflchat-dev://chat.iflgm.com/login/desktop?server_token=abc&isDesktopDev=true');
    });

    test('never mattermost://', () => {
        expect(iflDesktopHandoffURL('http://localhost:8065/login/desktop?server_token=x')).not.toMatch(/^mattermost/);
    });
});
