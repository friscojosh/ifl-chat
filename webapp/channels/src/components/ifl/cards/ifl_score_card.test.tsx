// Copyright (c) 2015-present Mattermost, Inc. All Rights Reserved.
// See LICENSE.txt for license information.

// IFL: new file. The score card (app cards): iflgm.com's ScoreCard as its
// chat panel draws it.

import React from 'react';

import {Client4} from 'mattermost-redux/client';

import {resetTeamBadgesForTest} from 'components/ifl/team_badges/store';

import {act, fireEvent, renderWithContext as render, screen, within} from 'tests/react_testing_utils';

import {IFL_LIVE_REFRESH_MS, resetIflCardsForTest} from './cards';
import IflScoreCard from './ifl_score_card';
import {answer, scoreBody} from './test_fixtures';

jest.mock('client/web_websocket_client', () => ({
    __esModule: true,
    default: {addMessageListener: jest.fn(), addReconnectListener: jest.fn()},
}));

const BADGES = {
    version: 'v1',
    teams: {LAC: {abbr: 'LAC', name: 'Los Angeles Chargers', conference: 'AFC', color: '#007BC7', logo_rev: 'aa11'}},
    users: {},
};

let score: () => Promise<Response>;
const fetchMock = jest.fn((url: string) => (url.endsWith('/ifl/team_badges') ? answer(200, BADGES) : score()));

const fallback = <p>{'MIA 88.3 at LAC 101.4'}</p>;

async function drawn(id = '4512') {
    render(
        <IflScoreCard
            id={id}
            fallback={fallback}
        />,
    );
    return screen.findByTestId('ifl-score-card');
}

function row(card: HTMLElement, abbr: string) {
    const rows = Array.from(card.querySelectorAll<HTMLElement>('.IflScoreCard__row'));
    return rows.find((r) => r.querySelector('.IflScoreCard__abbr')?.textContent === abbr)!;
}

describe('IflScoreCard', () => {
    beforeEach(() => {
        resetIflCardsForTest();
        resetTeamBadgesForTest();
        Client4.setUrl('http://chat.test');
        fetchMock.mockClear();
        score = () => answer(200, scoreBody());
        global.fetch = fetchMock as unknown as typeof fetch;
    });

    test('the message shows until the game loads, then the card', async () => {
        render(
            <IflScoreCard
                id='4512'
                fallback={fallback}
            />,
        );
        expect(screen.getByText('MIA 88.3 at LAC 101.4')).toBeInTheDocument();
        await screen.findByTestId('ifl-score-card');
        expect(screen.queryByText('MIA 88.3 at LAC 101.4')).toBeNull();
        expect(fetchMock).toHaveBeenCalledWith('http://chat.test/api/v4/ifl/cards/score/4512', expect.objectContaining({method: 'get'}));
    });

    test('live: pulsing LIVE, the week, records, starters left and live scores; away first', async () => {
        const card = await drawn();
        expect(within(card).getByText('LIVE')).toHaveClass('IflScoreCard__status--live');
        expect(within(card).getByText('Wk 12')).toBeInTheDocument();
        const rows = card.querySelectorAll('.IflScoreCard__row');
        expect(rows[0]).toHaveTextContent('MIA');
        expect(rows[1]).toHaveTextContent('LAC');
        expect(row(card, 'MIA')).toHaveTextContent('6-5(0)88.25');
        expect(row(card, 'LAC')).toHaveTextContent('7-4(2)101.4');
        expect(within(row(card, 'LAC')).getByTitle('2 yet to play')).toBeInTheDocument();
        expect(card.querySelector('.IflScoreCard__row--winner')).toBeNull();
    });

    test('the whole card opens the box score on iflgm.com in a new tab', async () => {
        const card = await drawn();
        expect(card.tagName).toBe('A');
        expect(card).toHaveAttribute('href', 'https://iflgm.com/live/12?matchup=4512');
        expect(card).toHaveAttribute('target', '_blank');
        expect(card).toHaveAttribute('rel', 'noopener noreferrer');
        expect(card).toHaveAccessibleName('Miami Dolphins at Los Angeles Chargers, week 12: open the box score on iflgm.com');
    });

    test('final: FINAL, the winner marked, no starters left', async () => {
        score = () => answer(200, scoreBody({status: 'final', home_score: 120.5, away_score: 99}));
        const card = await drawn();
        expect(within(card).getByText('FINAL')).toHaveClass('IflScoreCard__status--final');
        expect(row(card, 'LAC')).toHaveClass('IflScoreCard__row--winner');
        expect(row(card, 'MIA')).not.toHaveClass('IflScoreCard__row--winner');
        expect(row(card, 'LAC')).toHaveTextContent('7-4120.5');
        expect(card.querySelector('.IflScoreCard__left')).toBeNull();
    });

    test('live with nobody left on either side shows FINAL', async () => {
        score = () => answer(200, scoreBody({home_left: 0, away_left: 0}));
        const card = await drawn();
        expect(within(card).getByText('FINAL')).toBeInTheDocument();
        expect(row(card, 'LAC')).toHaveClass('IflScoreCard__row--winner');
    });

    test('upcoming: dashes for scores', async () => {
        score = () => answer(200, scoreBody({status: 'scheduled', home_live_score: null, away_live_score: null, home_left: null, away_left: null}));
        const card = await drawn();
        expect(within(card).getByText('UPCOMING')).toHaveClass('IflScoreCard__status--scheduled');
        expect(row(card, 'LAC')).toHaveTextContent('7-4-');
    });

    test("logos come from chat's logo route with the logo's revision; a missing one is the abbreviation", async () => {
        const card = await drawn();
        await act(async () => {
            await Promise.resolve();
        });
        const logo = row(card, 'LAC').querySelector('img')!;
        expect(logo.getAttribute('src')).toBe('http://chat.test/api/v4/ifl/team_badges/logos/LAC.png?s=64&v=aa11');
        expect(logo).toHaveAttribute('width', '29');
        fireEvent.error(logo);
        expect(row(card, 'LAC').querySelector('img')).toBeNull();
        expect(row(card, 'LAC').querySelector('.IflCardLogo--text')).toHaveTextContent('LAC');
    });

    test('a game chat cannot read keeps the message', async () => {
        score = () => answer(404, {id: 'ifl.cards.not_found'});
        render(
            <IflScoreCard
                id='999'
                fallback={fallback}
            />,
        );
        await act(async () => {
            await Promise.resolve();
        });
        expect(screen.getByText('MIA 88.3 at LAC 101.4')).toBeInTheDocument();
        expect(screen.queryByTestId('ifl-score-card')).toBeNull();
    });

    describe('refresh', () => {
        beforeEach(() => {
            jest.useFakeTimers();
        });
        afterEach(() => {
            jest.useRealTimers();
        });

        const scoreCalls = () => fetchMock.mock.calls.filter(([url]) => url.includes('/ifl/cards/score/')).length;

        test('a live game refetches every minute while the tab is visible', async () => {
            await drawn();
            expect(scoreCalls()).toBe(1);

            score = () => answer(200, scoreBody({home_live_score: 110.1}));
            await act(async () => {
                jest.advanceTimersByTime(IFL_LIVE_REFRESH_MS);
            });
            expect(scoreCalls()).toBe(2);
            expect(await screen.findByText('110.1')).toBeInTheDocument();

            const visibility = jest.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');
            await act(async () => {
                jest.advanceTimersByTime(IFL_LIVE_REFRESH_MS);
            });
            expect(scoreCalls()).toBe(2);
            visibility.mockRestore();
        });

        test('a final game does not refetch', async () => {
            score = () => answer(200, scoreBody({status: 'final', home_score: 1, away_score: 2}));
            await drawn();
            await act(async () => {
                jest.advanceTimersByTime(IFL_LIVE_REFRESH_MS * 3);
            });
            expect(scoreCalls()).toBe(1);
        });
    });
});
