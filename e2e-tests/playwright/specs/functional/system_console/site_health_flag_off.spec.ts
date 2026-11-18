// Copyright (c) 2015-present Mattermost, Inc. All Rights Reserved.
// See LICENSE.txt for license information.

import {openSystemConsoleSection, expect, test} from '@mattermost/playwright-lib';

import {skipUnlessEnterprise} from './site_health_support';

test('hides Site health when the feature flag is off', {tag: '@system_console'}, async ({pw}) => {
    await skipUnlessEnterprise(pw);
    await pw.ensureFeatureFlag('HealthDashboard', false);

    const {adminUser} = await pw.initSetup();
    const {app} = await pw.testBrowser.login(adminUser);

    // # Open the System Console
    await openSystemConsoleSection(app);

    // * Verify Reporting is listed but Site health is not
    const reporting = app.admin.sidebar.category('reporting');
    await expect(reporting.section('system_analytics').titleLink).toBeVisible();
    await expect(reporting.section('site_health')).toHaveCount(0);
});
