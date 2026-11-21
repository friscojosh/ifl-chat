// Copyright (c) 2015-present Mattermost, Inc. All Rights Reserved.
// See LICENSE.txt for license information.

// IFL: new file. Tests for the IFL Chat branding on the signed-out pages.

import React from 'react';

import {renderWithContext, screen} from 'tests/react_testing_utils';

import Header from './header';
import IflFooter from './ifl_footer';

describe('IFL Chat branding on the signed-out pages', () => {
    const unlicensed = {
        entities: {
            general: {
                config: {SiteName: 'Mattermost'},
                license: {IsLicensed: 'false'},
            },
        },
    };

    test('header shows the IFL Chat icon and name, with no edition badge', () => {
        renderWithContext(<Header/>, unlicensed);

        const link = screen.getByRole('link', {name: 'IFL Chat'});
        expect(link).toHaveAttribute('href', '/');
        expect(screen.getByTestId('ifl-header-brand')).toHaveTextContent('IFL Chat');
        expect(link.querySelector('img.ifl-header-brand__icon')).not.toBeNull();
        expect(link.querySelector('svg')).toBeNull();
        expect(screen.queryByText('TEAM EDITION')).not.toBeInTheDocument();
        expect(screen.queryByText(/Mattermost/)).not.toBeInTheDocument();
    });

    test('footer shows the league copyright and an iflgm.com link only', () => {
        renderWithContext(
            <IflFooter/>,
            {
                entities: {
                    general: {
                        config: {
                            AboutLink: 'https://mattermost.com/about',
                            HelpLink: 'https://mattermost.com/help',
                            PrivacyPolicyLink: 'https://mattermost.com/privacy',
                            TermsOfServiceLink: 'https://mattermost.com/terms',
                        },
                    },
                },
            },
        );

        expect(screen.getByTestId('footer-copyright')).toHaveTextContent(`© ${new Date().getFullYear()} International Fantasy League`);
        const links = screen.getAllByRole('link');
        expect(links).toHaveLength(1);
        expect(links[0]).toHaveAttribute('href', 'https://iflgm.com');
        expect(links[0]).toHaveTextContent('iflgm.com');
        expect(screen.queryByText(/Mattermost/)).not.toBeInTheDocument();
    });
});
