// Copyright (c) 2015-present Mattermost, Inc. All Rights Reserved.
// See LICENSE.txt for license information.

// IFL: new file. Tests for ifl_client_config.ts.

import type {ClientConfig} from '@mattermost/types/config';

import {GeneralTypes} from 'mattermost-redux/action_types';
import reducer from 'mattermost-redux/reducers/entities/general';

import {iflClientConfig, isMattermostLink} from './ifl_client_config';

const stock: Partial<ClientConfig> = {
    SiteName: 'IFL Chat',
    AppDownloadLink: 'https://mattermost.com/pl/download-apps',
    IosAppDownloadLink: 'https://mattermost.com/pl/ios-app/',
    AndroidAppDownloadLink: 'https://mattermost.com/pl/android-app/',
    HelpLink: 'https://mattermost.com/pl/help/',
    ReportAProblemType: 'default',
    ReportAProblemLink: 'https://mattermost.com/pl/report-a-bug',
    EnableAskCommunityLink: 'true',
};

describe('iflClientConfig', () => {
    test('drops the stock mattermost.com links and hides report a problem', () => {
        expect(iflClientConfig(stock)).toEqual({
            SiteName: 'IFL Chat',
            AppDownloadLink: '',
            IosAppDownloadLink: '',
            AndroidAppDownloadLink: '',
            HelpLink: '',
            ReportAProblemType: 'hidden',
            ReportAProblemLink: '',
            EnableAskCommunityLink: 'false',
        });
    });

    test('keeps links an admin pointed elsewhere', () => {
        const config = {...stock, HelpLink: 'https://iflgm.com/help', ReportAProblemType: 'link', ReportAProblemLink: 'https://iflgm.com/report'};
        const result = iflClientConfig(config);
        expect(result.HelpLink).toBe('https://iflgm.com/help');
        expect(result.ReportAProblemType).toBe('link');
        expect(result.ReportAProblemLink).toBe('https://iflgm.com/report');
    });

    test('isMattermostLink', () => {
        expect(isMattermostLink('https://docs.mattermost.com/x')).toBe(true);
        expect(isMattermostLink('http://mattermost.com')).toBe(true);
        expect(isMattermostLink('https://mattermost.com.evil.example')).toBe(false);
        expect(isMattermostLink('https://iflgm.com')).toBe(false);
        expect(isMattermostLink('')).toBe(false);
        expect(isMattermostLink(undefined)).toBe(false);
    });

    test('the config reducer applies it', () => {
        const state = reducer(undefined, {type: GeneralTypes.CLIENT_CONFIG_RECEIVED, data: stock});
        expect(state.config.AppDownloadLink).toBe('');
        expect(state.config.SiteName).toBe('IFL Chat');
    });
});
