// Copyright (c) 2015-present Mattermost, Inc. All Rights Reserved.
// See LICENSE.txt for license information.

// IFL: new file. IFL Chat in the About dialog (about_build_modal.tsx): its
// icon, a credit to the Mattermost edition it is built on, and a link to the
// corresponding source (AGPL section 13), and the iflgm.com link that replaces
// Mattermost's terms and privacy links. Mattermost's copyright line and
// open-source notice stay in the dialog.

import React from 'react';

import ExternalLink from 'components/external_link';
import {IFL_SITE_LABEL, IFL_SITE_URL} from 'components/header_footer_route/ifl_branding';

import iflChatIcon128 from 'images/ifl_chat_icon_128.png';

export const IFL_SOURCE_REPO = 'https://github.com/friscojosh/ifl-chat';
const IFL_SOURCE_LABEL = 'github.com/friscojosh/ifl-chat';
const CREDIT_BEFORE_EDITION = 'Built on Mattermost ';
const CREDIT_AFTER_EDITION = ', open source software. Source code: ';

// The server's BuildHash is the commit the image was built from (IFL.md).
export function iflSourceUrl(buildHash?: string): string {
    if (buildHash && (/^[0-9a-f]{7,40}$/).test(buildHash)) {
        return `${IFL_SOURCE_REPO}/tree/${buildHash}`;
    }
    return IFL_SOURCE_REPO;
}

export function IflAboutIcon() {
    return (
        <img
            src={iflChatIcon128}
            width={104}
            height={104}
            alt=''
            style={{borderRadius: 22}}
        />
    );
}

type CreditProps = {
    edition: React.ReactNode;
    buildHash?: string;
};

export function IflAboutCredit({edition, buildHash}: CreditProps) {
    return (
        <div data-testid='ifl-about-credit'>
            {CREDIT_BEFORE_EDITION}{edition}{CREDIT_AFTER_EDITION}
            <ExternalLink
                location='about_build_modal'
                href={iflSourceUrl(buildHash)}
            >
                {IFL_SOURCE_LABEL}
            </ExternalLink>
        </div>
    );
}

export function IflSiteLink() {
    return (
        <ExternalLink
            location='about_build_modal'
            href={IFL_SITE_URL}
        >
            {IFL_SITE_LABEL}
        </ExternalLink>
    );
}
