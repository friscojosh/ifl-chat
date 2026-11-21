// Copyright (c) 2015-present Mattermost, Inc. All Rights Reserved.
// See LICENSE.txt for license information.

// IFL: new file. The team chip after a GM's name (IFL Chat apps plan).

import {act, fireEvent, render, screen} from '@testing-library/react';
import React from 'react';

import {Client4} from 'mattermost-redux/client';

import WebSocketClient from 'client/web_websocket_client';

import IflTeamChip from './ifl_team_chip';
import {IFL_TEAM_BADGES_EVENT, resetTeamBadgesForTest} from './store';
import type {IflBadges} from './store';

jest.mock('client/web_websocket_client', () => ({
    __esModule: true,
    default: {addMessageListener: jest.fn(), addReconnectListener: jest.fn()},
}));

const BADGES: IflBadges = {
    version: 'v1',
    teams: {
        LAC: {abbr: 'LAC', name: 'Los Angeles Chargers', conference: 'AFC', color: '#007BC7', logo_rev: 'aa11'},
        MIA: {abbr: 'MIA', name: 'Miami Dolphins', conference: 'AFC', color: '#008E97', logo_rev: 'bb22'},
    },
    users: {gm1: 'LAC'},
};

function answer(status: number, body?: unknown) {
    return Promise.resolve({status, ok: status >= 200 && status < 300, json: async () => body} as Response);
}

const fetchMock = jest.fn();

function lastListener(mock: unknown) {
    const calls = (mock as jest.Mock).mock.calls;
    return calls[calls.length - 1][0];
}

describe('IflTeamChip', () => {
    beforeEach(() => {
        resetTeamBadgesForTest();
        Client4.setUrl('http://chat.test');
        fetchMock.mockReset();
        fetchMock.mockImplementation(() => answer(200, BADGES));
        global.fetch = fetchMock as unknown as typeof fetch;
    });

    test('a GM gets their team logo, named for screen readers', async () => {
        render(<IflTeamChip userId='gm1'/>);
        const img = await screen.findByRole('img', {name: 'Los Angeles Chargers · AFC'});
        expect(img.getAttribute('src')).toBe('http://chat.test/api/v4/ifl/team_badges/logos/LAC.png?s=64&v=aa11');
        expect(fetchMock).toHaveBeenCalledWith('http://chat.test/api/v4/ifl/team_badges', expect.objectContaining({method: 'get'}));
    });

    test('nothing for a member without a team', async () => {
        render(<IflTeamChip userId='someone'/>);
        await act(async () => {
            await Promise.resolve();
        });
        expect(screen.queryByRole('img')).toBeNull();
    });

    test('a logo that fails becomes the abbreviation on the team colour', async () => {
        render(<IflTeamChip userId='gm1'/>);
        fireEvent.error(await screen.findByRole('img', {name: 'Los Angeles Chargers · AFC'}));
        const chip = screen.getByRole('img', {name: 'Los Angeles Chargers · AFC'});
        expect(chip.textContent).toBe('LAC');
        expect(chip).toHaveStyle({backgroundColor: '#007BC7'});
    });

    test('the event refetches with the version; a move shows, a 304 keeps', async () => {
        render(<IflTeamChip userId='gm1'/>);
        await screen.findByRole('img', {name: 'Los Angeles Chargers · AFC'});
        const listener = lastListener(WebSocketClient.addMessageListener);

        fetchMock.mockImplementationOnce(() => answer(304));
        await act(async () => {
            listener({event: IFL_TEAM_BADGES_EVENT, data: {version: 'v1'}, broadcast: {}, seq: 2});
        });
        expect(fetchMock).toHaveBeenLastCalledWith('http://chat.test/api/v4/ifl/team_badges', expect.objectContaining({
            headers: expect.objectContaining({'If-None-Match': 'v1'}),
        }));
        expect(screen.getByRole('img', {name: 'Los Angeles Chargers · AFC'})).toBeInTheDocument();

        fetchMock.mockImplementationOnce(() => answer(200, {...BADGES, version: 'v2', users: {gm1: 'MIA'}}));
        await act(async () => {
            listener({event: IFL_TEAM_BADGES_EVENT, data: {version: 'v2'}, broadcast: {}, seq: 3});
        });
        expect(await screen.findByRole('img', {name: 'Miami Dolphins · AFC'})).toBeInTheDocument();
    });

    test('other events, errors and malformed answers change nothing', async () => {
        render(<IflTeamChip userId='gm1'/>);
        await screen.findByRole('img', {name: 'Los Angeles Chargers · AFC'});
        const listener = lastListener(WebSocketClient.addMessageListener);
        await act(async () => {
            listener({event: 'posted', data: {}, broadcast: {}, seq: 4});
        });
        expect(fetchMock).toHaveBeenCalledTimes(1);

        fetchMock.mockImplementationOnce(() => Promise.reject(new Error('offline')));
        await act(async () => {
            lastListener(WebSocketClient.addReconnectListener)();
        });
        fetchMock.mockImplementationOnce(() => answer(200, {version: 'v9', teams: 'nope'}));
        await act(async () => {
            listener({event: IFL_TEAM_BADGES_EVENT, data: {}, broadcast: {}, seq: 5});
        });
        expect(screen.getByRole('img', {name: 'Los Angeles Chargers · AFC'})).toBeInTheDocument();
    });
});
