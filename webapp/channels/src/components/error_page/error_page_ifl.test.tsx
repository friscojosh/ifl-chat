// Copyright (c) 2015-present Mattermost, Inc. All Rights Reserved.
// See LICENSE.txt for license information.

// IFL: new file. The signed error links name the site (IFL Chat), not Mattermost.

import crypto from 'crypto';
import React from 'react';

import {renderWithContext, screen} from 'tests/react_testing_utils';
import {ErrorPageTypes} from 'utils/constants';

import ErrorPage from './error_page';

describe('ErrorPage back link (IFL)', () => {
    const {publicKey, privateKey} = crypto.generateKeyPairSync('ec', {namedCurve: 'prime256v1'});
    const publicKeyBase64 = publicKey.export({type: 'spki', format: 'der'}).toString('base64');

    function signedSearch(type: string) {
        const params = new URLSearchParams({type, returnTo: '/league/channels/town-square'});
        const sign = crypto.createSign('sha256');
        sign.update('/error?' + params.toString());
        params.append('s', sign.sign(privateKey, 'base64'));
        return '?' + params.toString();
    }

    it.each([
        ErrorPageTypes.PERMALINK_NOT_FOUND,
        ErrorPageTypes.CLOUD_ARCHIVED,
    ])('%s links back to the site name', (type) => {
        renderWithContext(
            <ErrorPage
                location={{search: signedSearch(type)}}
                asymmetricSigningPublicKey={publicKeyBase64}
                siteName='IFL Chat'
            />,
        );

        expect(screen.getByRole('link', {name: 'Back to IFL Chat'})).toHaveAttribute('href', '/league/channels/town-square');
        expect(screen.queryByText(/Mattermost/)).not.toBeInTheDocument();
    });
});
