// Copyright (c) 2015-present Mattermost, Inc. All Rights Reserved.
// See LICENSE.txt for license information.

// IFL: new file. The signed-out pages' footer: the league copyright and a link
// to iflgm.com, in place of upstream's footer.tsx (Mattermost copyright and the
// About, Privacy Policy, Terms and Help links). header_footer_route.tsx loads it.

import React from 'react';

import ExternalLink from 'components/external_link';

import {IFL_SITE_LABEL, IFL_SITE_URL, iflCopyright} from './ifl_branding';

import './footer.scss';

const IflFooter = () => {
    // As upstream's footer: no footer in an embedded view
    if (document.cookie.includes('MMEMBED=1')) {
        return null;
    }

    return (
        <div
            data-testid='hfroute-footer'
            className='hfroute-footer'
        >
            <span
                className='footer-copyright'
                data-testid='footer-copyright'
            >
                {iflCopyright()}
            </span>
            <ExternalLink
                className='footer-link'
                href={IFL_SITE_URL}
                location='footer'
            >
                {IFL_SITE_LABEL}
            </ExternalLink>
        </div>
    );
};

export default IflFooter;
