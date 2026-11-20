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

// Query parameters that carry something to show the member (or a flow the
// redirect must not cut short). redirect_to is not one: it is forwarded.
const BLOCKING_PARAMS = ['extra', 'error', 'message', 'server_token'];

function safely<T>(fn: () => T, fallback: T): T {
    try {
        return fn();
    } catch {
        return fallback;
    }
}

export function markSignedOut() {
    safely(() => localStorage.setItem(SIGNED_OUT_KEY, '1'), undefined);
}

export function clearSignedOut() {
    safely(() => localStorage.removeItem(SIGNED_OUT_KEY), undefined);
}

export function wasSignedOut(): boolean {
    return safely(() => localStorage.getItem(SIGNED_OUT_KEY) === '1', false);
}

export function recordAttempt() {
    safely(() => sessionStorage.setItem(ATTEMPT_KEY, String(Date.now())), undefined);
}

export function hasRecentAttempt(): boolean {
    const at = safely(() => Number(sessionStorage.getItem(ATTEMPT_KEY)), 0);
    return Boolean(at) && Date.now() - at < IFL_ATTEMPT_WINDOW_MS;
}

export function shouldAutoSignIn(onlyIflgm: boolean, search: string): boolean {
    if (!onlyIflgm || isDesktopApp() || isEmbedded()) {
        return false;
    }
    const params = new URLSearchParams(search);
    if (BLOCKING_PARAMS.some((name) => params.has(name))) {
        return false;
    }
    return !wasSignedOut() && !hasRecentAttempt();
}

export function startSignIn(url: string) {
    recordAttempt();
    window.location.assign(url);
}
