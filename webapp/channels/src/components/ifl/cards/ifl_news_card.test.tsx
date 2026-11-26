// Copyright (c) 2015-present Mattermost, Inc. All Rights Reserved.
// See LICENSE.txt for license information.

// IFL: new file. The news card (app cards): iflgm.com's NewsStory, compact,
// as its chat panel draws it.

import React from 'react';

import {Client4} from 'mattermost-redux/client';

import {resetTeamBadgesForTest} from 'components/ifl/team_badges/store';

import {act, renderWithContext, screen, within} from 'tests/react_testing_utils';

import {parseNewsCard, resetIflCardsForTest} from './cards';
import IflNewsCard, {IflNewsCardView, relativeTime} from './ifl_news_card';
import {answer, newsBody} from './test_fixtures';

jest.mock('client/web_websocket_client', () => ({
    __esModule: true,
    default: {addMessageListener: jest.fn(), addReconnectListener: jest.fn()},
}));

let news: () => Promise<Response>;
const fetchMock = jest.fn((url: string) => (url.endsWith('/ifl/team_badges') ? answer(200, {version: 'v', teams: {}, users: {}}) : news()));

const NOW = new Date('2026-11-25T17:30:00Z');

function view(body = newsBody(), imageProxy = false) {
    const {container} = renderWithContext(
        <IflNewsCardView
            story={parseNewsCard(body)!}
            now={NOW}
        />,
        {entities: {general: {config: {HasImageProxy: imageProxy ? 'true' : 'false'}}}},
    );
    return within(container).getByTestId('ifl-news-card');
}

describe('IflNewsCard', () => {
    beforeEach(() => {
        resetIflCardsForTest();
        resetTeamBadgesForTest();
        Client4.setUrl('http://chat.test');
        fetchMock.mockClear();
        news = () => answer(200, newsBody());
        global.fetch = fetchMock as unknown as typeof fetch;
    });

    test('the message shows until the story loads, then the card', async () => {
        renderWithContext(
            <IflNewsCard
                id='rw-123'
                fallback={<p>{'Herbert limited'}</p>}
            />,
        );
        expect(screen.getByText('Herbert limited')).toBeInTheDocument();
        await screen.findByTestId('ifl-news-card');
        expect(screen.queryByText('Herbert limited')).toBeNull();
        expect(fetchMock).toHaveBeenCalledWith('http://chat.test/api/v4/ifl/cards/news/rw-123', expect.objectContaining({method: 'get'}));
    });

    test('a story chat cannot read keeps the message', async () => {
        news = () => answer(502, {id: 'ifl.cards.unavailable'});
        renderWithContext(
            <IflNewsCard
                id='rw-123'
                fallback={<p>{'Herbert limited'}</p>}
            />,
        );
        await act(async () => {
            await Promise.resolve();
        });
        expect(screen.getByText('Herbert limited')).toBeInTheDocument();
        expect(screen.queryByTestId('ifl-news-card')).toBeNull();
    });

    test('the player, when, headline, text and source', () => {
        const card = view();
        const name = within(card).getByRole('link', {name: 'Justin Herbert'});
        expect(name).toHaveAttribute('href', 'https://iflgm.com/player/9');
        expect(name).toHaveAttribute('target', '_blank');
        expect(within(card).getByText('QB · LAC')).toBeInTheDocument();
        expect(within(card).getByText('Your player')).toBeInTheDocument();
        expect(within(card).getByText('2 hours ago').tagName).toBe('TIME');
        expect(within(card).getByRole('heading', {name: 'Herbert limited at practice'})).toBeInTheDocument();
        expect(within(card).getByText('Justin Herbert (ankle) was limited Wednesday.')).toBeInTheDocument();
        expect(within(card).getByText('RotoWire')).toBeInTheDocument();
    });

    test("the headshot is iflgm.com's, through the image proxy when chat has one", () => {
        expect(view().querySelector('.IflNewsCard__headshot img')).toHaveAttribute('src', 'https://iflgm.com/headshots/13589.png?v=3');
        const card = view(newsBody(), true);
        expect(card.querySelector('.IflNewsCard__headshot img')).toHaveAttribute('src', `http://chat.test/api/v4/image?url=${encodeURIComponent('https://iflgm.com/headshots/13589.png?v=3')}`);
    });

    test('owners per conference: logo and abbreviation, or Free agent', () => {
        const card = view();
        const owners = within(card).getByLabelText('Owners');
        const afc = within(owners).getByText('AFC').parentElement!;
        const team = within(afc).getByRole('link', {name: 'LAC'});
        expect(team).toHaveAttribute('href', 'https://iflgm.com/team/16');
        expect(team).toHaveAttribute('title', 'Los Angeles Chargers');
        expect(team.querySelector('img')).toHaveAttribute('src', 'http://chat.test/api/v4/ifl/team_badges/logos/LAC.png?s=64');
        const nfc = within(owners).getByText('NFC').parentElement!;
        expect(nfc).toHaveTextContent('NFCFree agent');
        expect(nfc).toHaveClass('IflNewsCard__owner--free');
    });

    test('not your player: no chip; no logo key: the abbreviation', () => {
        const card = view(newsBody({owners: {NFC: {id: 3, abbreviation: 'XYZ', name: 'Somebody', mine: false, badge_abbr: null}}}));
        expect(within(card).queryByText('Your player')).toBeNull();
        const nfc = within(card).getByRole('link', {name: 'XYZ'});
        expect(nfc.querySelector('img')).toBeNull();
        expect(within(card).getByText('AFC').parentElement).toHaveTextContent('AFCFree agent');
    });

    test('a story without a player: no name, no owners, the NFL face', () => {
        const card = view(newsBody({player: null, owners: {}}));
        expect(within(card).queryByRole('link')).toBeNull();
        expect(within(card).queryByLabelText('Owners')).toBeNull();
        expect(card.querySelector('.IflNewsCard__noface')).toHaveTextContent('NFL');
    });

    test('relative time as the site says it', () => {
        expect(relativeTime('2026-11-25T17:29:30Z', NOW)).toBe('just now');
        expect(relativeTime('2026-11-25T17:29:00Z', NOW)).toBe('1 minute ago');
        expect(relativeTime('2026-11-25T16:30:00', NOW)).toBe('1 hour ago');
        expect(relativeTime('2026-11-22T17:30:00Z', NOW)).toBe('3 days ago');
    });
});
