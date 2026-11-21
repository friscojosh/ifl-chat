// Copyright (c) 2015-present Mattermost, Inc. All Rights Reserved.
// See LICENSE.txt for license information.

// IFL: new file. Every GM's team chip (IFL Chat apps plan), from
// GET /api/v4/ifl/team_badges. Fetched on first use, again when the server
// sends custom_ifl_team_badges_changed and after a reconnect. A 304, an error
// or a malformed answer keeps the last good badges.

import {useSyncExternalStore} from 'react';

import {Client4} from 'mattermost-redux/client';

import WebSocketClient from 'client/web_websocket_client';

export type IflBadgeTeam = {abbr: string; name: string; conference: string; color: string; logo_rev: string};
export type IflBadges = {version: string; teams: Record<string, IflBadgeTeam>; users: Record<string, string>};

export const IFL_TEAM_BADGES_EVENT = 'custom_ifl_team_badges_changed';

const EMPTY: IflBadges = {version: '', teams: {}, users: {}};

let current: IflBadges = EMPTY;
let running: Promise<void> | null = null;
let again = false;
let started = false;
const listeners = new Set<() => void>();

export function parseBadges(raw: unknown): IflBadges | null {
    if (!raw || typeof raw !== 'object') {
        return null;
    }
    const r = raw as Record<string, unknown>;
    if (typeof r.version !== 'string' || !r.teams || typeof r.teams !== 'object' || !r.users || typeof r.users !== 'object') {
        return null;
    }
    const teams: Record<string, IflBadgeTeam> = {};
    for (const [key, value] of Object.entries(r.teams as Record<string, unknown>)) {
        const t = value as Partial<IflBadgeTeam> | null;
        if (t && t.abbr === key && (/^[A-Z]{2,3}$/).test(key) && typeof t.name === 'string' &&
            typeof t.conference === 'string' && typeof t.color === 'string' && (/^#[0-9A-Fa-f]{6}$/).test(t.color)) {
            teams[key] = {abbr: key, name: t.name, conference: t.conference, color: t.color, logo_rev: typeof t.logo_rev === 'string' ? t.logo_rev : ''};
        }
    }
    const users: Record<string, string> = {};
    for (const [id, abbr] of Object.entries(r.users as Record<string, unknown>)) {
        if (typeof abbr === 'string' && teams[abbr]) {
            users[id] = abbr;
        }
    }
    return {version: r.version, teams, users};
}

async function fetchOnce() {
    const headers: Record<string, string> = {};
    if (current.version) {
        headers['If-None-Match'] = current.version;
    }
    try {
        const res = await fetch(`${Client4.getBaseRoute()}/ifl/team_badges`, Client4.getOptions({method: 'get', headers}));
        if (res.status !== 200) {
            return;
        }
        const next = parseBadges(await res.json());
        if (next) {
            current = next;
            listeners.forEach((l) => l());
        }
    } catch {
        // Keep the last good badges: never an error in front of members.
    }
}

/** Refetch now; a call during a fetch runs one more fetch after it. */
export function refreshTeamBadges(): Promise<void> {
    if (running) {
        again = true;
        return running;
    }
    running = (async () => {
        do {
            again = false;
            // eslint-disable-next-line no-await-in-loop
            await fetchOnce();
        } while (again);
    })().finally(() => {
        running = null;
    });
    return running;
}

// Typed by the one field read, so no WebSocketMessage import is needed.
function onMessage(msg: {event: string}) {
    if (msg.event === IFL_TEAM_BADGES_EVENT) {
        refreshTeamBadges();
    }
}

function start() {
    if (started) {
        return;
    }
    started = true;
    WebSocketClient.addMessageListener(onMessage);
    WebSocketClient.addReconnectListener(() => {
        refreshTeamBadges();
    });
    refreshTeamBadges();
}

function subscribe(listener: () => void) {
    start();
    listeners.add(listener);
    return () => {
        listeners.delete(listener);
    };
}

function getSnapshot() {
    return current;
}

export function useIflTeamBadge(userId: string): IflBadgeTeam | undefined {
    const badges = useSyncExternalStore(subscribe, getSnapshot);
    const abbr = badges.users[userId];
    return abbr ? badges.teams[abbr] : undefined;
}

export function teamLogoUrl(team: IflBadgeTeam, size: 64 | 128): string {
    return `${Client4.getBaseRoute()}/ifl/team_badges/logos/${encodeURIComponent(team.abbr)}.png?s=${size}&v=${encodeURIComponent(team.logo_rev)}`;
}

export function resetTeamBadgesForTest() {
    current = EMPTY;
    running = null;
    again = false;
    started = false;
    listeners.clear();
}
