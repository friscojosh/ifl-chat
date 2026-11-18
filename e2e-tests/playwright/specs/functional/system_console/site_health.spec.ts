// Copyright (c) 2015-present Mattermost, Inc. All Rights Reserved.
// See LICENSE.txt for license information.

// TODO: Add a full e2e test of the health dashboard with real findings once an admin can trigger a health check run.

import {openSystemConsoleSection, expect, test} from '@mattermost/playwright-lib';

import {skipUnlessEnterprise} from './site_health_support';

/**
 * @objective Verify a system admin can open the Site health page and it loads findings without an error.
 *
 * @precondition
 * Full (Testcontainers) mode, so the server can be restarted with the HealthDashboard feature flag on.
 */
test('shows the Site health page to a system admin', {tag: '@system_console'}, async ({pw}) => {
    await skipUnlessEnterprise(pw);
    await pw.ensureFeatureFlag('HealthDashboard', true);

    const {adminUser} = await pw.initSetup();
    const {app} = await pw.testBrowser.login(adminUser);

    // # Open Reporting > Site health
    await openSystemConsoleSection(app);
    await app.admin.sidebar.category('reporting').section('site_health').titleLink.click();

    // * Verify the page loaded from the findings API without an error: either not evaluated yet or evaluated
    const {health} = app.admin;
    await expect(app.admin.header).toHaveText('Site health');
    await expect(health.notEvaluated.locator.or(health.lastEvaluatedText.locator)).toBeVisible();
    await expect(health.loadError).toHaveCount(0);
});
