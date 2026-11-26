// Copyright (c) 2015-present Mattermost, Inc. All Rights Reserved.
// See LICENSE.txt for license information.

// IFL: new file. Card posts in the post list (app cards): the card replaces
// the message and the fallback attachment once it loads; until then, or when
// it cannot load, the post is drawn as any other.

import React from 'react';

import type {Post, PostMetadata} from '@mattermost/types/posts';

import {Client4} from 'mattermost-redux/client';
import type {Theme} from 'mattermost-redux/selectors/entities/preferences';

import PostBodyAdditionalContent from 'components/post_view/post_body_additional_content/post_body_additional_content';
import PostMessageView from 'components/post_view/post_message_view/post_message_view';

import {act, renderWithContext, screen} from 'tests/react_testing_utils';

import {resetIflCardsForTest} from './cards';
import {answer, newsBody, scoreBody} from './test_fixtures';

jest.mock('components/post_markdown', () => jest.fn((props: {message: string}) => <div data-testid='post-markdown'>{props.message}</div>));
jest.mock('plugins/pluggable', () => jest.fn(() => null));
jest.mock('components/post_view/message_attachments/message_attachment_list', () => ({
    __esModule: true,
    default: jest.fn(() => <div data-testid='message-attachment-list'/>),
}));
jest.mock('client/web_websocket_client', () => ({
    __esModule: true,
    default: {addMessageListener: jest.fn(), addReconnectListener: jest.fn()},
}));

let site: (url: string) => Promise<Response>;
const fetchMock = jest.fn((url: string) => (url.endsWith('/ifl/team_badges') ? answer(200, {version: 'v', teams: {}, users: {}}) : site(url)));

function cardPost(type: string, props: Record<string, unknown>): Post {
    return {
        id: 'post1',
        channel_id: 'ch1',
        type,
        message: '**Miami Dolphins** 88.3 at **Los Angeles Chargers** 101.4',
        props: {...props, attachments: [{fallback: 'score', title: 'Week 12 · Live'}]},
        metadata: {embeds: [{type: 'message_attachment'}], images: {}} as unknown as PostMetadata,
    } as unknown as Post;
}

function drawPost(post: Post) {
    return renderWithContext(
        <PostBodyAdditionalContent
            post={post}
            appsEnabled={false}
            mmBlocksEnabled={false}
            actions={{toggleEmbedVisibility: jest.fn()}}
        >
            <PostMessageView
                post={post}
                enableFormatting={true}
                theme={{} as Theme}
                currentRelativeTeamUrl='/team'
                isChannelAutotranslated={false}
                userLanguage='en'
            />
        </PostBodyAdditionalContent>,
    );
}

const flush = () => act(async () => {
    await Promise.resolve();
});

describe('card posts', () => {
    beforeEach(() => {
        resetIflCardsForTest();
        Client4.setUrl('http://chat.test');
        fetchMock.mockClear();
        site = (url) => answer(200, url.includes('/score/') ? scoreBody() : newsBody());
        global.fetch = fetchMock as unknown as typeof fetch;
    });

    test('a score post: message and attachment, then the card alone', async () => {
        drawPost(cardPost('custom_ifl_score', {ifl_score: {v: 1, id: '4512'}}));
        expect(screen.getByTestId('post-markdown')).toBeInTheDocument();
        expect(screen.getByTestId('message-attachment-list')).toBeInTheDocument();
        await screen.findByTestId('ifl-score-card');
        expect(screen.queryByTestId('post-markdown')).toBeNull();
        expect(screen.queryByTestId('message-attachment-list')).toBeNull();
    });

    test('a news post: the card alone once the story loads', async () => {
        drawPost(cardPost('custom_ifl_news', {ifl_news: {v: 1, id: 'rw-123'}}));
        await screen.findByTestId('ifl-news-card');
        expect(screen.queryByTestId('post-markdown')).toBeNull();
        expect(screen.queryByTestId('message-attachment-list')).toBeNull();
    });

    test('a card chat cannot read: message and attachment stay', async () => {
        site = () => answer(404, {id: 'ifl.cards.not_found'});
        drawPost(cardPost('custom_ifl_score', {ifl_score: {v: 1, id: '999'}}));
        await flush();
        expect(screen.getByTestId('post-markdown')).toBeInTheDocument();
        expect(screen.getByTestId('message-attachment-list')).toBeInTheDocument();
        expect(screen.queryByTestId('ifl-score-card')).toBeNull();
    });

    test('a malformed card or another post type is never fetched', async () => {
        drawPost(cardPost('custom_ifl_score', {ifl_score: {v: 1, id: 'abc'}}));
        drawPost(cardPost('', {ifl_score: {v: 1, id: '4512'}}));
        await flush();
        expect(fetchMock).not.toHaveBeenCalled();
        expect(screen.getAllByTestId('message-attachment-list')).toHaveLength(2);
    });
});
