// Copyright (c) 2015-present Mattermost, Inc. All Rights Reserved.
// See LICENSE.txt for license information.

// IFL: new file. A league team's logo on a card (app cards), from chat's
// public logo route; the abbreviation in a box, as iflgm.com's TeamLogo
// falls back, when the team has no logo or it fails to load.

import React, {useState} from 'react';

import {useIflBadgeTeam} from 'components/ifl/team_badges/store';

import {iflCardLogoUrl} from './cards';

type Props = {
    badgeAbbr: string | null;
    abbreviation: string;
    px: number;
};

export default function IflCardLogo({badgeAbbr, abbreviation, px}: Props) {
    const team = useIflBadgeTeam(badgeAbbr);
    const [failed, setFailed] = useState<string | null>(null);
    const src = badgeAbbr ? iflCardLogoUrl(badgeAbbr, team?.logo_rev) : null;
    if (!src || failed === src) {
        return (
            <span
                className='IflCardLogo IflCardLogo--text'
                style={{width: px, height: px, fontSize: Math.max(px * 0.35, 9)}}
                aria-hidden={true}
            >
                {abbreviation}
            </span>
        );
    }
    return (
        <img
            className='IflCardLogo'
            src={src}
            width={px}
            height={px}
            alt=''
            onError={() => setFailed(src)}
        />
    );
}
