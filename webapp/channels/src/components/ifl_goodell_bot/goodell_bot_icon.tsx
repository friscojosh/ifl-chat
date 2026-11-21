// Copyright (c) 2015-present Mattermost, Inc. All Rights Reserved.
// See LICENSE.txt for license information.

// IFL: new file. Avatar for system messages, which IFL Chat shows as posted by
// "Goodell Bot": the Goodell Bot picture in place of the Mattermost logo (see
// IFL.md).

import React from 'react';

import goodellBotImage from 'images/goodell_bot.png';

type Props = {
    className?: string;
    size?: number;
};

const GoodellBotIcon = ({className, size = 32}: Props) => (
    <span
        className={className}
        data-testid='goodell-bot-icon'
    >
        <img
            src={goodellBotImage}
            width={size}
            height={size}
            style={{borderRadius: '50%', objectFit: 'cover'}}
            alt=''
        />
    </span>
);

export default GoodellBotIcon;
