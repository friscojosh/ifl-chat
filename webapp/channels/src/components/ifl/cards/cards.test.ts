// Copyright (c) 2015-present Mattermost, Inc. All Rights Reserved.
// See LICENSE.txt for license information.

// IFL: new file. Card posts, the site's data as the site's frontend maps it,
// and loading (app cards).

import type {Post} from '@mattermost/types/posts';

import {Client4} from 'mattermost-redux/client';

import {iflCardRef, loadIflCard, parseNewsCard, parseScoreCard, resetIflCardsForTest, shownStatus} from './cards';
import {answer, newsBody, scoreBody} from './test_fixtures';

const post = (type: string, props: Record<string, unknown>) => ({type, props} as unknown as Pick<Post, 'type' | 'props'>);

describe('iflCardRef', () => {
    test('score and news posts with a well-formed card', () => {
        expect(iflCardRef(post('custom_ifl_score', {ifl_score: {v: 1, id: '4512'}}))).toEqual({kind: 'score', id: '4512'});
        expect(iflCardRef(post('custom_ifl_news', {ifl_news: {v: 1, id: 'rw-123'}}))).toEqual({kind: 'news', id: 'rw-123'});
    });

    test.each([
        ['another type', post('custom_ifl_trade', {ifl_score: {v: 1, id: '4512'}})],
        ['no card', post('custom_ifl_score', {})],
        ['another version', post('custom_ifl_score', {ifl_score: {v: 2, id: '4512'}})],
        ['a numeric id', post('custom_ifl_score', {ifl_score: {v: 1, id: 4512}})],
        ['a non-digit matchup id', post('custom_ifl_score', {ifl_score: {v: 1, id: '45a'}})],
        ['a 13-digit matchup id', post('custom_ifl_score', {ifl_score: {v: 1, id: '1234567890123'}})],
        ['a story id with a slash', post('custom_ifl_news', {ifl_news: {v: 1, id: '../x'}})],
        ['a story id with a space', post('custom_ifl_news', {ifl_news: {v: 1, id: 'a b'}})],
        ['a 41-character story id', post('custom_ifl_news', {ifl_news: {v: 1, id: 'x'.repeat(41)}})],
        ['the score prop on a news post', post('custom_ifl_news', {ifl_score: {v: 1, id: '4512'}})],
    ])('null for %s', (_, p) => {
        expect(iflCardRef(p)).toBeNull();
    });
});

describe('parseScoreCard', () => {
    test('live with live scores: the provisional scores', () => {
        const g = parseScoreCard(scoreBody())!;
        expect(g).toMatchObject({id: '4512', weekNum: 12, status: 'live', homeScore: 101.4, awayScore: 88.25, homeRecord: '7-4', homeLeft: 2, awayLeft: 0});
        expect(g.homeTeam).toEqual({id: 16, name: 'Los Angeles Chargers', abbreviation: 'LAC', badgeAbbr: 'LAC'});
    });

    test('live without live scores, and final: the official scores', () => {
        expect(parseScoreCard(scoreBody({home_live_score: null, away_live_score: null, home_score: 90, away_score: 80}))).toMatchObject({homeScore: 90, awayScore: 80});
        expect(parseScoreCard(scoreBody({status: 'final', home_score: 120.5, away_score: 99}))).toMatchObject({status: 'final', homeScore: 120.5, awayScore: 99});
    });

    test('unknowns stay unknown; a team without a logo key has none', () => {
        const g = parseScoreCard(scoreBody({status: 'scheduled', home_left: null, home_record: null, away_team: {id: 20, name: 'Miami Dolphins', abbreviation: 'MIA', badge_abbr: null}}))!;
        expect(g.homeLeft).toBeUndefined();
        expect(g.homeRecord).toBeUndefined();
        expect(g.homeScore).toBeUndefined();
        expect(g.awayTeam?.badgeAbbr).toBeNull();
    });

    test('not a card', () => {
        expect(parseScoreCard(null)).toBeNull();
        expect(parseScoreCard({week: {}})).toBeNull();
    });

    test('a live game with nobody left on either side shows as final', () => {
        expect(shownStatus({status: 'live', homeLeft: 0, awayLeft: 0})).toBe('final');
        expect(shownStatus({status: 'live', homeLeft: 0, awayLeft: 1})).toBe('live');
        expect(shownStatus({status: 'live'})).toBe('live');
        expect(shownStatus({status: 'scheduled', homeLeft: 0, awayLeft: 0})).toBe('scheduled');
    });
});

describe('parseNewsCard', () => {
    test('the story, its player and owners', () => {
        expect(parseNewsCard(newsBody())).toEqual({
            id: 'rw-123',
            title: 'Herbert limited at practice',
            content: 'Justin Herbert (ankle) was limited Wednesday.',
            source: 'RotoWire',
            publishedAt: '2026-11-25T15:00:00+00:00',
            player: {id: 9, mflId: '13589', name: 'Justin Herbert', position: 'QB', nflTeam: 'LAC'},
            owners: {AFC: {id: 16, abbreviation: 'LAC', name: 'Los Angeles Chargers', mine: true, badgeAbbr: 'LAC'}},
        });
    });

    test('a story without a player', () => {
        expect(parseNewsCard(newsBody({player: null, owners: {}}))).toMatchObject({player: null, owners: {}});
    });

    test('not a story', () => {
        expect(parseNewsCard({item: {id: 'x'}})).toBeNull();
        expect(parseNewsCard({})).toBeNull();
    });
});

describe('loadIflCard', () => {
    const fetchMock = jest.fn();

    beforeEach(() => {
        resetIflCardsForTest();
        Client4.setUrl('http://chat.test');
        fetchMock.mockReset();
        global.fetch = fetchMock as unknown as typeof fetch;
    });

    test('score cards drawn within 15 s share one request', async () => {
        fetchMock.mockImplementation(() => answer(200, scoreBody()));
        await loadIflCard({kind: 'score', id: '4512'}, 1000);
        await loadIflCard({kind: 'score', id: '4512'}, 15_999);
        expect(fetchMock).toHaveBeenCalledTimes(1);
        expect(fetchMock).toHaveBeenCalledWith('http://chat.test/api/v4/ifl/cards/score/4512', expect.objectContaining({method: 'get'}));
        await loadIflCard({kind: 'score', id: '4512'}, 16_000);
        expect(fetchMock).toHaveBeenCalledTimes(2);
    });

    test('concurrent loads share one request', async () => {
        fetchMock.mockImplementation(() => answer(200, scoreBody()));
        await Promise.all([loadIflCard({kind: 'score', id: '1'}), loadIflCard({kind: 'score', id: '1'})]);
        expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    test('a story is read once; a failed one is tried again', async () => {
        fetchMock.mockImplementationOnce(() => answer(502, {id: 'ifl.cards.unavailable'}));
        await loadIflCard({kind: 'news', id: 'rw-123'});
        fetchMock.mockImplementation(() => answer(200, newsBody()));
        await loadIflCard({kind: 'news', id: 'rw-123'});
        await loadIflCard({kind: 'news', id: 'rw-123'}, Date.now() + 3_600_000);
        expect(fetchMock).toHaveBeenCalledTimes(2);
        expect(fetchMock).toHaveBeenLastCalledWith('http://chat.test/api/v4/ifl/cards/news/rw-123', expect.anything());
    });
});
