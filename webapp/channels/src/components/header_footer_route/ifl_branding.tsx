// Copyright (c) 2015-present Mattermost, Inc. All Rights Reserved.
// See LICENSE.txt for license information.

// IFL: new file. IFL Chat branding for the signed-out pages (login, signup and
// the other pages under HFRoute): the app icon and name in the header, the
// league tagline, and the league footer. Replaces Mattermost's logo, edition
// badge, tagline and footer there (see IFL.md).

import React from 'react';

import iflChatIcon128 from 'images/ifl_chat_icon_128.png';
import iflChatIcon64 from 'images/ifl_chat_icon_64.png';

import './ifl_branding.scss';

export const IFL_APP_NAME = 'IFL Chat';
export const IFL_LEAGUE_NAME = 'International Fantasy League';
export const IFL_TAGLINE = 'League chat for the International Fantasy League';
export const IFL_SITE_URL = 'https://iflgm.com';
export const IFL_SITE_LABEL = 'iflgm.com';

export const IflHeaderBrand = () => (
    <span
        className='ifl-header-brand'
        data-testid='ifl-header-brand'
    >
        <img
            className='ifl-header-brand__icon'
            src={iflChatIcon64}
            srcSet={`${iflChatIcon64} 1x, ${iflChatIcon128} 2x`}
            width={40}
            height={40}
            alt=''
        />
        <span className='ifl-header-brand__name'>{IFL_APP_NAME}</span>
    </span>
);

export const iflCopyright = () => `© ${new Date().getFullYear()} ${IFL_LEAGUE_NAME}`;
