// Copyright (c) 2015-present Mattermost, Inc. All Rights Reserved.
// See LICENSE.txt for license information.

// IFL: new file. The hooks for score and news card posts (app cards):
// PostMessageView draws the card in place of the message once it loads, and
// PostBodyAdditionalContent drops the post's fallback attachment while the
// card shows. Any other post, or a card that has not loaded (or cannot), is
// untouched.

import React from 'react';

import type {Post} from '@mattermost/types/posts';

import {iflCardRef, useIflCardValue} from './cards';
import IflNewsCard from './ifl_news_card';
import IflScoreCard from './ifl_score_card';

/** The post's card, falling back to `message` until it loads. */
export function iflPostCard(post: Pick<Post, 'type' | 'props'>, message: React.ReactNode): React.ReactNode {
    const ref = iflCardRef(post);
    if (!ref) {
        return message;
    }
    return ref.kind === 'score' ? (
        <IflScoreCard
            key={`score/${ref.id}`}
            id={ref.id}
            fallback={message}
        />
    ) : (
        <IflNewsCard
            key={`news/${ref.id}`}
            id={ref.id}
            fallback={message}
        />
    );
}

/** The post's attachments, unless its card is showing in their place. */
export function IflCardAttachments({post, children}: {post: Pick<Post, 'type' | 'props'>; children: React.ReactNode}) {
    const ref = iflCardRef(post);
    const card = useIflCardValue(ref);
    if (ref && card !== undefined) {
        return null;
    }
    return <>{children}</>;
}
