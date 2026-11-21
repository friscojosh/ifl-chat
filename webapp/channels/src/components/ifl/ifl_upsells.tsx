// Copyright (c) 2015-present Mattermost, Inc. All Rights Reserved.
// See LICENSE.txt for license information.

// IFL: new file. IFL Chat is a self-hosted Team Edition fork with nothing to
// buy, so it offers no Enterprise trial, upgrade, licence purchase or "contact
// sales". Upstream's trial and pricing modals never open, the upsell buttons,
// badges and banners render nothing, and the System Console drops its feature
// discovery ("try Enterprise") pages and the Edition and License page. Each hook
// that uses these is marked `// IFL:` (see IFL.md).

import type {AdminDefinition} from 'components/admin_console/types';

import {ModalIdentifiers} from 'utils/constants';

import {IFL_UPSELLS} from './ifl_features';

// Modals that only sell: trials, pricing, purchases, "notify your admin to
// upgrade", "this feature is restricted" and "contact sales".
export const IFL_UPSELL_MODALS: ReadonlySet<string> = new Set([
    ModalIdentifiers.START_TRIAL_MODAL,
    ModalIdentifiers.START_TRIAL_FORM_MODAL,
    ModalIdentifiers.START_TRIAL_FORM_MODAL_RESULT,
    ModalIdentifiers.TRIAL_BENEFITS_MODAL,
    ModalIdentifiers.LEARN_MORE_TRIAL_MODAL,
    ModalIdentifiers.THREE_DAYS_LEFT_TRIAL_MODAL,
    ModalIdentifiers.PRICING_MODAL,
    ModalIdentifiers.FEATURE_RESTRICTED_MODAL,
    ModalIdentifiers.CONFIRM_NOTIFY_ADMIN,
    ModalIdentifiers.UPGRADE_CLOUD_ACCOUNT,
    ModalIdentifiers.CLOUD_PURCHASE,
    ModalIdentifiers.CLOUD_LIMITS,
    ModalIdentifiers.SELF_HOSTED_PURCHASE,
    ModalIdentifiers.SELF_HOSTED_EXPANSION,
    ModalIdentifiers.AIR_GAPPED_SELF_HOSTED_PURCHASE,
    ModalIdentifiers.AIR_GAPPED_CONTACT_SALES,
    ModalIdentifiers.UPGRADE_EXPORT_DATA_MODAL,
]);

// True for a modal IFL Chat never opens.
export function isIFLUpsellModal(modalId: string): boolean {
    return !IFL_UPSELLS && IFL_UPSELL_MODALS.has(modalId);
}

function IFLNoUpsell() {
    return null;
}

// An upsell component: renders nothing in IFL Chat.
export function iflNoUpsell<C>(Component: C): C {
    return (IFL_UPSELLS ? Component : IFLNoUpsell) as C;
}

// System Console pages that only sell: Team Edition's Edition and License page
// (upgrade to Enterprise, start a trial, compare plans).
const IFL_UPSELL_CONSOLE_PAGES: ReadonlyArray<[string, string]> = [
    ['about', 'license'],
];

// The System Console without upsells: feature discovery pages and the pages
// above are hidden (from the sidebar, search and routes), and no item shows a
// "paid feature" indicator.
export function iflAdminDefinition<T extends AdminDefinition>(definition: T): T {
    if (IFL_UPSELLS) {
        return definition;
    }
    for (const [sectionKey, section] of Object.entries(definition)) {
        for (const [subsectionKey, subsection] of Object.entries(section.subsections)) {
            if (subsection.isDiscovery || IFL_UPSELL_CONSOLE_PAGES.some(([s, ss]) => s === sectionKey && ss === subsectionKey)) {
                subsection.isHidden = true;
            }
            delete subsection.restrictedIndicator;
        }
    }
    return definition;
}
