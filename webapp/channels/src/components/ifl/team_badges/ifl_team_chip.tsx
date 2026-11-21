// Copyright (c) 2015-present Mattermost, Inc. All Rights Reserved.
// See LICENSE.txt for license information.

// IFL: new file. A GM's team logo after their name (IFL Chat apps plan); the
// abbreviation on the team colour if the logo does not load. Nothing for
// bots and members without a team.

import React, {useState} from 'react';

import {IFL_TEAM_CHIPS} from 'components/ifl/ifl_features';

import {teamLogoUrl, useIflTeamBadge} from './store';

import './ifl_team_chip.scss';

type Props = {
    userId: string;
    size?: 16 | 20;
};

export default function IflTeamChip({userId, size = 16}: Props) {
    const team = useIflTeamBadge(userId);
    const [failed, setFailed] = useState<string | null>(null);
    if (!IFL_TEAM_CHIPS || !team) {
        return null;
    }
    const label = team.conference ? `${team.name} · ${team.conference}` : team.name;
    const logoKey = `${team.abbr}:${team.logo_rev}`;
    if (!team.logo_rev || failed === logoKey) {
        return (
            <span
                className='IflTeamChip IflTeamChip--text'
                role='img'
                aria-label={label}
                title={label}
                style={{backgroundColor: team.color}}
            >
                {team.abbr}
            </span>
        );
    }
    return (
        <img
            className='IflTeamChip'
            src={teamLogoUrl(team, 64)}
            width={size}
            height={size}
            alt={label}
            title={label}
            onError={() => setFailed(logoKey)}
        />
    );
}
