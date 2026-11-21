// Copyright (c) 2015-present Mattermost, Inc. All Rights Reserved.
// See LICENSE.txt for license information.

// IFL: new file. System messages in a permalink preview show the Goodell Bot avatar.

import React from 'react';

import {renderWithContext, screen} from 'tests/react_testing_utils';
import {TestHelper} from 'utils/test_helper';

import PreviewPostAvatar from './avatar';

describe('PreviewPostAvatar', () => {
    const user = TestHelper.getUserMock({id: 'user_id'});

    test('shows the Goodell Bot avatar for a system message', () => {
        renderWithContext(
            <PreviewPostAvatar
                user={user}
                post={TestHelper.getPostMock({user_id: user.id, type: 'system_join_leave'})}
            />,
        );

        const img = screen.getByTestId('goodell-bot-icon').querySelector('img');
        expect(img).toHaveAttribute('width', '24');
        expect(img).toHaveStyle({borderRadius: '50%'});
    });

    test('shows the user avatar for a regular post', () => {
        renderWithContext(
            <PreviewPostAvatar
                user={user}
                post={TestHelper.getPostMock({user_id: user.id, type: ''})}
            />,
        );

        expect(screen.queryByTestId('goodell-bot-icon')).not.toBeInTheDocument();
    });
});
