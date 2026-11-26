// Copyright (c) 2015-present Mattermost, Inc. All Rights Reserved.
// See LICENSE.txt for license information.

// IFL: new file. A league game shared to chat, drawn as iflgm.com's Live
// Scoring draws it (the site's ScoreCard, as its chat panel shows it) and kept
// current while the game is on. The whole card opens the box score on
// iflgm.com.

import classNames from 'classnames';
import React from 'react';

import ExternalLink from 'components/external_link';

import {iflLiveUrl, shownStatus, useIflCard, useIflLiveRefresh} from './cards';
import type {IflCardTeam, IflMatchupStatus, IflScoreCardData} from './cards';
import IflCardLogo from './ifl_card_logo';

import './ifl_cards.scss';

const STATUS_LABEL: Record<IflMatchupStatus, string> = {live: 'LIVE', final: 'FINAL', scheduled: 'UPCOMING'};

/** The site's logo size 24, drawn 1.2x as the site's TeamLogo draws it. */
const LOGO_PX = 29;

// The site's full-size card shows the score as it is (no rounding).
const fmt = (n?: number) => (n == null ? '-' : String(n));

type RowProps = {
    team?: IflCardTeam;
    record?: string;
    left?: number;
    showLeft: boolean;
    score?: number;
    winner: boolean;
};

function TeamRow({team, record, left, showLeft, score, winner}: RowProps) {
    const abbr = team?.abbreviation ?? '?';
    return (
        <div className={classNames('IflScoreCard__row', {'IflScoreCard__row--winner': winner})}>
            <div className='IflScoreCard__team'>
                <IflCardLogo
                    badgeAbbr={team?.badgeAbbr ?? null}
                    abbreviation={abbr}
                    px={LOGO_PX}
                />
                <span className='IflScoreCard__abbr'>{abbr}</span>
                {record && <span className='IflScoreCard__record'>{record}</span>}
            </div>
            {showLeft && left != null && (
                <span
                    className='IflScoreCard__left'
                    title={`${left} yet to play`}
                >
                    {`(${left})`}
                </span>
            )}
            <span className='IflScoreCard__score'>{fmt(score)}</span>
        </div>
    );
}

export function IflScoreCardView({game}: {game: IflScoreCardData}) {
    const status = shownStatus(game);
    const isFinal = status === 'final';

    // "(n)" while the game is on.
    const showLeft = status === 'live';
    const homeWinning = (game.homeScore ?? 0) > (game.awayScore ?? 0);
    const awayWinning = (game.awayScore ?? 0) > (game.homeScore ?? 0);
    const away = game.awayTeam?.name ?? 'Away';
    const home = game.homeTeam?.name ?? 'Home';
    return (
        <ExternalLink
            className='IflScoreCard'
            href={iflLiveUrl(game.id, game.weekNum)}
            location='ifl_score_card'
            aria-label={`${away} at ${home}, week ${game.weekNum}: open the box score on iflgm.com`}
            data-testid='ifl-score-card'
        >
            <div className='IflScoreCard__header'>
                <span className={`IflScoreCard__status IflScoreCard__status--${status}`}>{STATUS_LABEL[status]}</span>
                <span className='IflScoreCard__week'>{`Wk ${game.weekNum}`}</span>
            </div>
            <TeamRow
                team={game.awayTeam}
                record={game.awayRecord}
                left={game.awayLeft}
                showLeft={showLeft}
                score={game.awayScore}
                winner={isFinal && awayWinning}
            />
            <TeamRow
                team={game.homeTeam}
                record={game.homeRecord}
                left={game.homeLeft}
                showLeft={showLeft}
                score={game.homeScore}
                winner={isFinal && homeWinning}
            />
        </ExternalLink>
    );
}

/** The card for a score post; the fallback until the game loads. */
export default function IflScoreCard({id, fallback}: {id: string; fallback: React.ReactNode}) {
    const ref = {kind: 'score' as const, id};
    const game = useIflCard<IflScoreCardData>(ref);
    useIflLiveRefresh(ref, game ? shownStatus(game) === 'live' : false);
    if (!game) {
        return <>{fallback}</>;
    }
    return <IflScoreCardView game={game}/>;
}
