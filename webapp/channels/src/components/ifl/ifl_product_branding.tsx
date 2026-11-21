// Copyright (c) 2015-present Mattermost, Inc. All Rights Reserved.
// See LICENSE.txt for license information.

// IFL: new file. The IFL Chat icon and name at the top left of the signed-in
// app (inside the product menu button), in place of the Mattermost logo and
// the "TEAM EDITION" badge.

import React from 'react';

import {IFL_APP_NAME} from 'components/header_footer_route/ifl_branding';

import iflChatIcon64 from 'images/ifl_chat_icon_64.png';

import './ifl_product_branding.scss';

export default function IflProductBranding() {
    return (
        <span
            className='globalHeader-leftControls-productBranding-ifl'
            data-testid='ifl-product-branding'
        >
            <img
                className='globalHeader-leftControls-productBranding-ifl-icon'
                src={iflChatIcon64}
                width={24}
                height={24}
                alt=''
            />
            <span className='globalHeader-leftControls-productBranding-ifl-name'>
                {IFL_APP_NAME}
            </span>
        </span>
    );
}
