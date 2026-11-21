// Copyright (c) 2015-present Mattermost, Inc. All Rights Reserved.
// See LICENSE.txt for license information.

// IFL: new file. The client config keeps Mattermost's stock links (app
// downloads, help, "report a problem", "ask the community") unless an admin
// changes them. In IFL Chat they would send members to mattermost.com, so a
// link that still points there is dropped, which hides the menu items and
// prompts that use it. A link an admin sets to anywhere else is kept.

import type {ClientConfig} from '@mattermost/types/config';

const MATTERMOST_LINK = /^https?:\/\/([a-z0-9-]+\.)*mattermost\.com(\/|$)/i;

const LINK_KEYS = ['AppDownloadLink', 'IosAppDownloadLink', 'AndroidAppDownloadLink', 'HelpLink', 'ReportAProblemLink'] as const;

export function isMattermostLink(url?: string): boolean {
    return Boolean(url && MATTERMOST_LINK.test(url.trim()));
}

export function iflClientConfig<T extends Partial<ClientConfig>>(config: T): T {
    if (!config || typeof config !== 'object') {
        return config;
    }

    const result: T = {...config};
    for (const key of LINK_KEYS) {
        if (isMattermostLink(result[key])) {
            result[key] = '' as T[typeof key];
        }
    }

    if ('EnableAskCommunityLink' in result) {
        result.EnableAskCommunityLink = 'false';
    }

    // "default" means mattermost.com for an unlicensed server, and "link" with
    // no link left falls through to the same. "hidden" is no type, so
    // getReportAProblemLink returns '' and the menu items are hidden.
    if (result.ReportAProblemType === 'default' || (result.ReportAProblemType === 'link' && !result.ReportAProblemLink)) {
        result.ReportAProblemType = 'hidden';
    }

    return result;
}
