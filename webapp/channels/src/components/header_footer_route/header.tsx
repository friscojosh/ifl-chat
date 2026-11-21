// Copyright (c) 2015-present Mattermost, Inc. All Rights Reserved.
// See LICENSE.txt for license information.

import classNames from 'classnames';
import React from 'react';
import {Link} from 'react-router-dom';

import BackButton from 'components/common/back_button';

import './header.scss';
import {IFL_APP_NAME, IflHeaderBrand} from './ifl_branding'; // IFL: replaces the Mattermost logo, license and config imports

export type HeaderProps = {
    alternateLink?: React.ReactElement<any>;
    backButtonURL?: string;
    onBackButtonClick?: React.EventHandler<React.MouseEvent>;
};

const Header = ({alternateLink, backButtonURL, onBackButtonClick}: HeaderProps) => {
    // IFL: the IFL Chat icon and name, with no Mattermost logo or edition badge
    const freeBanner = null;
    const title: React.ReactNode = <IflHeaderBrand/>;
    const ariaLabel = IFL_APP_NAME;

    return (
        <div
            data-testid='hfroute-header'
            className={classNames('hfroute-header', {'has-free-banner': freeBanner, 'has-custom-site-name': title})}
        >
            <div className='header-main'>
                <div>
                    {freeBanner &&
                        <Link
                            data-testid='header-logo-link'
                            className='header-logo-link'
                            to='/'
                            aria-label={ariaLabel}
                        >
                            {freeBanner}
                        </Link>
                    }
                    {title &&
                        <Link
                            data-testid='header-logo-link'
                            className='header-logo-link'
                            to='/'
                            aria-label={ariaLabel}
                        >
                            {title}
                        </Link>
                    }
                </div>
                {alternateLink}
            </div>
            {onBackButtonClick && (
                <BackButton
                    className='header-back-button'
                    url={backButtonURL}
                    onClick={onBackButtonClick}
                />
            )}
        </div>
    );
};

export default Header;
