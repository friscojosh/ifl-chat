// Copyright (c) 2015-present Mattermost, Inc. All Rights Reserved.
// See LICENSE.txt for license information.

// IFL: new file. Site answers for the app card tests (shapes from iflgm.com's
// /internal/chat/cards/* as chat passes them through).

export function scoreBody(over: Record<string, unknown> = {}) {
    return {
        week: {id: 3, week_number: 12, is_playoff: false},
        matchup: {
            id: 4512,
            status: 'live',
            home_score: null,
            away_score: null,
            home_live_score: 101.4,
            away_live_score: 88.25,
            home_record: '7-4',
            away_record: '6-5',
            home_left: 2,
            away_left: 0,
            home_team: {id: 16, name: 'Los Angeles Chargers', abbreviation: 'LAC', logo_url: null, badge_abbr: 'LAC'},
            away_team: {id: 20, name: 'Miami Dolphins', abbreviation: 'MIA', logo_url: null, badge_abbr: 'MIA'},
            ...over,
        },
    };
}

export function newsBody(over: Record<string, unknown> = {}) {
    return {
        item: {
            id: 'rw-123',
            title: 'Herbert limited at practice',
            content: 'Justin Herbert (ankle) was limited Wednesday.',
            source: 'RotoWire',
            published_at: '2026-11-25T15:00:00+00:00',
            player: {id: 9, mfl_id: '13589', name: 'Justin Herbert', position: 'QB', nfl_team: 'LAC'},
            owners: {AFC: {id: 16, abbreviation: 'LAC', name: 'Los Angeles Chargers', logo_url: null, mine: true, badge_abbr: 'LAC'}},
            ...over,
        },
    };
}

export function answer(status: number, body?: unknown) {
    return Promise.resolve({status, ok: status >= 200 && status < 300, json: async () => body} as Response);
}
