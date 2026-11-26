// Copyright (c) 2015-present Mattermost, Inc. All Rights Reserved.
// See LICENSE.txt for license information.

// IFL: new file. The score and news cards members share from iflgm.com's
// chat panel (app cards). A card post carries only the game's or story's id:
//
//   type "custom_ifl_score", props.ifl_score = {v: 1, id: "<matchup id>"}
//   type "custom_ifl_news",  props.ifl_news  = {v: 1, id: "<story id>"}
//
// plus a one-line message and props.attachments (a stock attachment, for
// clients without this code). The card is drawn from the site's own copy,
// read through chat (GET /api/v4/ifl/cards/score/<id> and .../news/<id>), so
// it shows the game or story as iflgm.com has it. Until that arrives, or when
// it cannot be read, the post shows its message and attachment.

import {useEffect, useSyncExternalStore} from 'react';

import type {Post} from '@mattermost/types/posts';

import {Client4} from 'mattermost-redux/client';

import {IFL_SITE_URL} from 'components/header_footer_route/ifl_branding';
import {IFL_APP_CARDS} from 'components/ifl/ifl_features';

export const IFL_SCORE_POST_TYPE = 'custom_ifl_score';
export const IFL_NEWS_POST_TYPE = 'custom_ifl_news';

const MATCHUP_ID = /^\d{1,12}$/;
const STORY_ID = /^[^\s/?#]{1,40}$/;

export type IflCardRef = {kind: 'score' | 'news'; id: string};

function propId(post: Pick<Post, 'props'>, prop: string, pattern: RegExp): string | null {
    const card = (post.props as Record<string, unknown> | undefined)?.[prop];
    if (!card || typeof card !== 'object') {
        return null;
    }
    const {v, id} = card as {v?: unknown; id?: unknown};
    return v === 1 && typeof id === 'string' && pattern.test(id) ? id : null;
}

/** The card a post carries, or null for any other post (or a malformed card). */
export function iflCardRef(post: Pick<Post, 'type' | 'props'>): IflCardRef | null {
    if (!IFL_APP_CARDS) {
        return null;
    }
    const type = post.type as string;
    if (type === IFL_SCORE_POST_TYPE) {
        const id = propId(post, 'ifl_score', MATCHUP_ID);
        return id ? {kind: 'score', id} : null;
    }
    if (type === IFL_NEWS_POST_TYPE) {
        const id = propId(post, 'ifl_news', STORY_ID);
        return id ? {kind: 'news', id} : null;
    }
    return null;
}

/* ===== Site data ===== */

export type IflCardTeam = {
    id: number;
    name: string;
    abbreviation: string;

    /** Key for chat's logo route; null: no logo (the abbreviation shows). */
    badgeAbbr: string | null;
};

export type IflMatchupStatus = 'scheduled' | 'live' | 'final';

/** A game as the site's score card shows it (frontend mapMatchup). */
export type IflScoreCardData = {
    id: string;
    weekNum: number;
    status: IflMatchupStatus;
    homeTeam?: IflCardTeam;
    awayTeam?: IflCardTeam;
    homeScore?: number;
    awayScore?: number;
    homeRecord?: string;
    awayRecord?: string;

    /** Starters yet to play; undefined: not known. */
    homeLeft?: number;
    awayLeft?: number;
};

export type IflNewsOwner = {id: number; abbreviation: string; name: string; mine: boolean; badgeAbbr: string | null};

export type IflNewsCardData = {
    id: string;
    title: string;
    content: string;
    source: string;
    publishedAt: string | null;
    player: {id: number; mflId: string | null; name: string; position: string; nflTeam: string} | null;
    owners: Record<string, IflNewsOwner>;
};

type Raw = Record<string, unknown>;

const isObj = (v: unknown): v is Raw => Boolean(v) && typeof v === 'object' && !Array.isArray(v);
const num = (v: unknown): number | undefined => (typeof v === 'number' && Number.isFinite(v) ? v : undefined);
const str = (v: unknown): string | undefined => (typeof v === 'string' ? v : undefined);
const BADGE = /^[A-Z]{2,3}$/;
const badge = (v: unknown): string | null => (typeof v === 'string' && BADGE.test(v) ? v : null);

function cardTeam(t: unknown): IflCardTeam | undefined {
    if (!isObj(t) || typeof t.abbreviation !== 'string') {
        return undefined;
    }
    return {id: num(t.id) ?? 0, name: str(t.name) ?? t.abbreviation, abbreviation: t.abbreviation, badgeAbbr: badge(t.badge_abbr)};
}

/** The site's {week, matchup}, mapped as the site's frontend maps it. */
export function parseScoreCard(raw: unknown): IflScoreCardData | null {
    if (!isObj(raw) || !isObj(raw.matchup)) {
        return null;
    }
    const m = raw.matchup;
    const week = isObj(raw.week) ? raw.week : {};
    const status: IflMatchupStatus = m.status === 'live' || m.status === 'final' ? m.status : 'scheduled';

    // While a week is live, scores come from ESPN (provisional) until MFL
    // posts official results (frontend utils/api.ts mapMatchup).
    const provisional = status === 'live' && (m.home_live_score != null || m.away_live_score != null);
    return {
        id: String(m.id ?? ''),
        weekNum: num(week.week_number) ?? 0,
        status,
        homeTeam: cardTeam(m.home_team),
        awayTeam: cardTeam(m.away_team),
        homeScore: num(provisional ? m.home_live_score : m.home_score),
        awayScore: num(provisional ? m.away_live_score : m.away_score),
        homeRecord: str(m.home_record) || undefined,
        awayRecord: str(m.away_record) || undefined,
        homeLeft: num(m.home_left),
        awayLeft: num(m.away_left),
    };
}

/** The site's {item}. */
export function parseNewsCard(raw: unknown): IflNewsCardData | null {
    if (!isObj(raw) || !isObj(raw.item)) {
        return null;
    }
    const n = raw.item;
    if (typeof n.id !== 'string' || typeof n.title !== 'string') {
        return null;
    }
    const p = isObj(n.player) && num(n.player.id) !== undefined ? n.player : null;
    const owners: Record<string, IflNewsOwner> = {};
    if (isObj(n.owners)) {
        for (const [conf, t] of Object.entries(n.owners)) {
            if (isObj(t) && typeof t.abbreviation === 'string') {
                owners[conf] = {
                    id: num(t.id) ?? 0,
                    abbreviation: t.abbreviation,
                    name: str(t.name) ?? '',
                    mine: t.mine === true,
                    badgeAbbr: badge(t.badge_abbr),
                };
            }
        }
    }
    return {
        id: n.id,
        title: n.title,
        content: str(n.content) ?? '',
        source: str(n.source) ?? '',
        publishedAt: str(n.published_at) ?? null,
        player: p ? {
            id: num(p.id) as number,
            mflId: p.mfl_id == null || p.mfl_id === '' ? null : String(p.mfl_id),
            name: str(p.name) ?? '',
            position: str(p.position) ?? '',
            nflTeam: str(p.nfl_team) ?? '',
        } : null,
        owners,
    };
}

/** The status to show: a live game with nobody left to play on either side
 *  is over, even before MFL posts the official result (site shownStatus). */
export function shownStatus(m: Pick<IflScoreCardData, 'status' | 'homeLeft' | 'awayLeft'>): IflMatchupStatus {
    return m.status === 'live' && m.homeLeft === 0 && m.awayLeft === 0 ? 'final' : m.status;
}

/* ===== Links ===== */

/** The game's box score on Live Scoring. */
export function iflLiveUrl(matchupId: string, weekNum: number): string {
    return `${IFL_SITE_URL}/live/${weekNum}?matchup=${encodeURIComponent(matchupId)}`;
}

export function iflPlayerUrl(playerId: number): string {
    return `${IFL_SITE_URL}/player/${playerId}`;
}

export function iflTeamUrl(teamId: number): string {
    return `${IFL_SITE_URL}/team/${teamId}`;
}

export const IFL_NEWS_URL = `${IFL_SITE_URL}/news`;

/** Bumped by the site when headshots change in place (frontend utils/headshots.ts). */
const HEADSHOT_VERSION = 3;

export function iflHeadshotUrl(mflId: string): string {
    return `${IFL_SITE_URL}/headshots/${encodeURIComponent(mflId)}.png?v=${HEADSHOT_VERSION}`;
}

/** Chat's public team logo route; v (the logo's revision) when known. */
export function iflCardLogoUrl(badgeAbbr: string, logoRev?: string): string {
    const v = logoRev ? `&v=${encodeURIComponent(logoRev)}` : '';
    return `${Client4.getBaseRoute()}/ifl/team_badges/logos/${encodeURIComponent(badgeAbbr)}.png?s=64${v}`;
}

/* ===== Loading ===== */

/** While a game is on, its cards fetch the score again this often. */
export const IFL_LIVE_REFRESH_MS = 60_000;

/** Score cards for the same game drawn within this long share one request. */
const SCORE_FRESH_MS = 15_000;

type Entry = {value?: unknown; at: number; loading?: Promise<void>};

const entries = new Map<string, Entry>();
const listeners = new Set<() => void>();

function notify() {
    listeners.forEach((l) => l());
}

function subscribe(listener: () => void) {
    listeners.add(listener);
    return () => {
        listeners.delete(listener);
    };
}

const keyOf = (ref: IflCardRef) => `${ref.kind}/${ref.id}`;

/**
 * Reads a card unless a good copy is fresh (scores: 15 s; stories: for the
 * page's life). A failure keeps the last good copy, so a card that has shown
 * stays; one that never loaded is tried again the next time it is drawn.
 */
export function loadIflCard(ref: IflCardRef, now = Date.now()): Promise<void> {
    const key = keyOf(ref);
    const hit = entries.get(key);
    if (hit?.loading) {
        return hit.loading;
    }
    if (hit && hit.value !== undefined && (ref.kind === 'news' || now - hit.at < SCORE_FRESH_MS)) {
        return Promise.resolve();
    }
    const entry: Entry = hit ?? {at: 0};
    entry.loading = (async () => {
        try {
            const url = `${Client4.getBaseRoute()}/ifl/cards/${ref.kind}/${encodeURIComponent(ref.id)}`;
            const res = await fetch(url, Client4.getOptions({method: 'get'}));
            if (res.status !== 200) {
                return;
            }
            const raw = await res.json();
            const value = ref.kind === 'score' ? parseScoreCard(raw) : parseNewsCard(raw);
            if (value) {
                entry.value = value;
                entry.at = now;
                notify();
            }
        } catch {
            // Keep what we have: the post's message shows until a card loads.
        } finally {
            entry.loading = undefined;
        }
    })();
    entries.set(key, entry);
    return entry.loading;
}

/** The card's data once loaded (no fetch). */
export function useIflCardValue<T>(ref: IflCardRef | null): T | undefined {
    const key = ref ? keyOf(ref) : '';
    return useSyncExternalStore(subscribe, () => (key ? entries.get(key)?.value as T | undefined : undefined));
}

/** The card's data, fetched when first drawn. */
export function useIflCard<T>(ref: IflCardRef): T | undefined {
    const {kind, id} = ref;
    useEffect(() => {
        loadIflCard({kind, id});
    }, [kind, id]);
    return useIflCardValue<T>(ref);
}

/** A live score card refetches every minute while the tab is visible. */
export function useIflLiveRefresh(ref: IflCardRef, live: boolean) {
    const {kind, id} = ref;
    useEffect(() => {
        if (!live) {
            return undefined;
        }
        const timer = window.setInterval(() => {
            if (document.visibilityState === 'hidden') {
                return;
            }
            loadIflCard({kind, id});
        }, IFL_LIVE_REFRESH_MS);
        return () => window.clearInterval(timer);
    }, [kind, id, live]);
}

/** For tests. */
export function resetIflCardsForTest() {
    entries.clear();
    listeners.clear();
}
