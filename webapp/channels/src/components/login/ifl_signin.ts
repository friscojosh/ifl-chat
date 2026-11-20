// Copyright (c) 2015-present Mattermost, Inc. All Rights Reserved.
// See LICENSE.txt for license information.

// IFL: new file. Members sign in only through iflgm.com, which chat sees as a
// GitLab-shaped OAuth provider. This module keeps the IFL wording and the rules
// for sending the login page straight to iflgm.com (see IFL.md).

import {isDesktopApp} from '@mattermost/shared/utils/user_agent';

import {isEmbedded} from 'utils/embed';

export const IFL_SIGNIN_LABEL = 'Sign in with iflgm.com';
export const IFL_SIGNIN_CARD_TITLE = 'Sign in with your iflgm.com account';
export const IFL_SIGNIN_STATUS = 'Signing in with iflgm.com…';

// Set when the member signs out of chat, so the login page shows the button
// instead of signing straight back in. Cleared by an explicit sign-in or once
// the member is signed in again. localStorage, so other open tabs see it too.
const SIGNED_OUT_KEY = 'ifl_signed_out';

// When the login page last sent this tab to iflgm.com. An OAuth failure ends on
// /error, whose link leads back to /login; within this window the login page
// shows the button rather than redirecting again, so a refusal cannot loop.
const ATTEMPT_KEY = 'ifl_signin_attempt';
export const IFL_ATTEMPT_WINDOW_MS = 2 * 60 * 1000;

// The only query parameter the automatic sign-in forwards. Anything else
// (invite, desktop, hint or message parameters) means the page shows the button.
const ALLOWED_PARAM = 'redirect_to';

// The same relative-path check login.tsx applies to redirect_to.
const RELATIVE_PATH = /^\/([^/]|$)/;

// In-memory mirror, so marks hold for this page's lifetime even when storage
// cannot be written. Reads fail closed: if storage throws, the page shows the
// button rather than redirecting.
let memorySignedOut = false;
let memoryAttemptAt = 0;

export function markSignedOut() {
    memorySignedOut = true;
    try {
        localStorage.setItem(SIGNED_OUT_KEY, '1');
    } catch {
        // the in-memory mark still applies
    }
}

export function clearSignedOut() {
    memorySignedOut = false;
    try {
        localStorage.removeItem(SIGNED_OUT_KEY);
    } catch {
        // nothing stored to clear
    }
}

export function wasSignedOut(): boolean {
    if (memorySignedOut) {
        return true;
    }
    try {
        return localStorage.getItem(SIGNED_OUT_KEY) === '1';
    } catch {
        return true;
    }
}

export function recordAttempt() {
    memoryAttemptAt = Date.now();
    try {
        sessionStorage.setItem(ATTEMPT_KEY, String(memoryAttemptAt));
    } catch {
        // the in-memory mark still applies
    }
}

export function clearAttempt() {
    memoryAttemptAt = 0;
    try {
        sessionStorage.removeItem(ATTEMPT_KEY);
    } catch {
        // nothing stored to clear
    }
}

export function hasRecentAttempt(): boolean {
    const recent = (at: number) => Boolean(at) && Date.now() - at < IFL_ATTEMPT_WINDOW_MS;
    if (recent(memoryAttemptAt)) {
        return true;
    }
    try {
        return recent(Number(sessionStorage.getItem(ATTEMPT_KEY)));
    } catch {
        return true;
    }
}

// The automatic sign-in URL, or null when the page should show the button.
// Only a relative redirect_to is forwarded; any other parameter blocks it.
export function autoSignInUrl(onlyIflgm: boolean, search: string, oauthRoute: string): string | null {
    if (!onlyIflgm || isDesktopApp() || isEmbedded() || wasSignedOut() || hasRecentAttempt()) {
        return null;
    }
    const params = new URLSearchParams(search);
    for (const name of params.keys()) {
        if (name !== ALLOWED_PARAM) {
            return null;
        }
    }
    const redirectTo = params.getAll(ALLOWED_PARAM);
    if (redirectTo.length > 1) {
        return null;
    }
    const url = `${oauthRoute}/gitlab/login`;
    if (redirectTo.length === 0) {
        return url;
    }
    if (!RELATIVE_PATH.test(redirectTo[0])) {
        return null;
    }
    return `${url}?${ALLOWED_PARAM}=${encodeURIComponent(redirectTo[0])}`;
}

export function startSignIn(url: string) {
    recordAttempt();
    window.location.assign(url);
}
