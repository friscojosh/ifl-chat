// Copyright (c) 2015-present Mattermost, Inc. All Rights Reserved.
// See LICENSE.txt for license information.

// IFL: new file. A news story shared to chat, drawn as iflgm.com's League >
// NFL News draws it in its chat panel (NewsStory, compact): the player, when,
// the headline and text, who rosters him in each conference, and the source.
// Titles and text are third-party: plain React text only, never HTML.

import React, {useState} from 'react';
import {useSelector} from 'react-redux';

import {getConfig} from 'mattermost-redux/selectors/entities/general';

import ExternalLink from 'components/external_link';

import {getImageSrc} from 'utils/post_utils';

import {iflHeadshotUrl, iflPlayerUrl, iflTeamUrl, useIflCard} from './cards';
import type {IflNewsCardData} from './cards';
import IflCardLogo from './ifl_card_logo';

import './ifl_cards.scss';

const CONFERENCES = ['AFC', 'NFC'];

/** The site's owner chip logo size 18, drawn 1.2x as its TeamLogo draws it. */
const OWNER_LOGO_PX = 22;

/** RotoWire times without a zone are UTC (site NewsPanel parseNewsTime). */
export function parseNewsTime(iso: string): Date {
    const hasZone = (/(Z|[+-]\d\d:?\d\d)$/i).test(iso);
    return new Date(hasZone ? iso : `${iso}Z`);
}

/** "just now", "5 minutes ago", "2 hours ago", "3 days ago" (site relativeTime). */
export function relativeTime(iso: string, now: Date): string {
    const seconds = (now.getTime() - parseNewsTime(iso).getTime()) / 1000;
    if (!Number.isFinite(seconds) || seconds < 60) {
        return 'just now';
    }
    const plural = (n: number, unit: string) => `${n} ${unit}${n === 1 ? '' : 's'} ago`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) {
        return plural(minutes, 'minute');
    }
    const hours = Math.floor(minutes / 60);
    if (hours < 24) {
        return plural(hours, 'hour');
    }
    return plural(Math.floor(hours / 24), 'day');
}

function fullNewsTime(iso: string): string {
    return parseNewsTime(iso).toLocaleString(undefined, {dateStyle: 'full', timeStyle: 'short'});
}

function Headshot({mflId}: {mflId: string}) {
    const hasImageProxy = useSelector(getConfig).HasImageProxy === 'true';
    const [failed, setFailed] = useState(false);
    return (
        <span className='IflNewsCard__headshot'>
            {!failed && (
                <img
                    src={getImageSrc(iflHeadshotUrl(mflId), hasImageProxy)}
                    alt=''
                    loading='lazy'
                    onError={() => setFailed(true)}
                />
            )}
        </span>
    );
}

export function IflNewsCardView({story: n, now}: {story: IflNewsCardData; now: Date}) {
    const p = n.player;
    const yours = Object.values(n.owners).some((o) => o.mine);
    const iso = n.publishedAt ? parseNewsTime(n.publishedAt) : null;
    return (
        <article
            className='IflNewsCard'
            data-testid='ifl-news-card'
        >
            <div className='IflNewsCard__face'>
                {p?.mflId ? (
                    <Headshot mflId={p.mflId}/>
                ) : (
                    <span
                        className='IflNewsCard__noface'
                        aria-hidden={true}
                    >
                        {'NFL'}
                    </span>
                )}
            </div>
            <div className='IflNewsCard__body'>
                <div className='IflNewsCard__top'>
                    <div className='IflNewsCard__who'>
                        {p && (
                            <>
                                <ExternalLink
                                    href={iflPlayerUrl(p.id)}
                                    location='ifl_news_card'
                                >
                                    {p.name}
                                </ExternalLink>
                                <small>{[p.position, p.nflTeam].filter(Boolean).join(' · ')}</small>
                                {yours && <span className='IflNewsCard__yours'>{'Your player'}</span>}
                            </>
                        )}
                    </div>
                    {n.publishedAt && iso && !Number.isNaN(iso.getTime()) && (
                        <time
                            className='IflNewsCard__when'
                            dateTime={iso.toISOString()}
                            title={fullNewsTime(n.publishedAt)}
                        >
                            {relativeTime(n.publishedAt, now)}
                        </time>
                    )}
                </div>
                <h3 className='IflNewsCard__headline'>{n.title}</h3>
                {n.content && <p className='IflNewsCard__text'>{n.content}</p>}
                <div className='IflNewsCard__foot'>
                    {p && (
                        <div
                            className='IflNewsCard__owners'
                            aria-label='Owners'
                        >
                            {CONFERENCES.map((c) => {
                                const o = n.owners[c];
                                return (
                                    <span
                                        key={c}
                                        className={o ? 'IflNewsCard__owner' : 'IflNewsCard__owner IflNewsCard__owner--free'}
                                    >
                                        <span className='IflNewsCard__conf'>{c}</span>
                                        {o ? (
                                            <ExternalLink
                                                href={iflTeamUrl(o.id)}
                                                location='ifl_news_card'
                                                title={o.name}
                                            >
                                                <IflCardLogo
                                                    badgeAbbr={o.badgeAbbr}
                                                    abbreviation={o.abbreviation}
                                                    px={OWNER_LOGO_PX}
                                                />
                                                {o.abbreviation}
                                            </ExternalLink>
                                        ) : <span>{'Free agent'}</span>}
                                    </span>
                                );
                            })}
                        </div>
                    )}
                    {n.source && <span className='IflNewsCard__source'>{n.source}</span>}
                </div>
            </div>
        </article>
    );
}

/** The card for a news post; the fallback until the story loads. */
export default function IflNewsCard({id, fallback}: {id: string; fallback: React.ReactNode}) {
    const story = useIflCard<IflNewsCardData>({kind: 'news', id});
    if (!story) {
        return <>{fallback}</>;
    }
    return (
        <IflNewsCardView
            story={story}
            now={new Date()}
        />
    );
}
