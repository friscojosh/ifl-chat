// Copyright (c) 2015-present Mattermost, Inc. All Rights Reserved.
// See LICENSE.txt for license information.

// IFL: new file. IFL Chat offers no Enterprise trial, upgrade, licence purchase
// or "contact sales": the trial and pricing openers do nothing, the upsell
// components render nothing and the System Console has no upsell pages.

import React from 'react';
import {useSelector} from 'react-redux';

import type {DeepPartial} from '@mattermost/types/utilities';

import {Permissions} from 'mattermost-redux/constants';

import {openModal} from 'actions/views/modals';
import {modalState} from 'reducers/views/modals';
import {getShowLockedManageUserSettings} from 'selectors/admin_console';

import AdminDefinition from 'components/admin_console/admin_definition';
import FeatureDiscovery from 'components/admin_console/feature_discovery';
import TrialBanner from 'components/admin_console/license_settings/trial_banner/trial_banner';
import ContactUsButton from 'components/announcement_bar/contact_sales/contact_us';
import PurchaseLink from 'components/announcement_bar/purchase_link/purchase_link';
import ShowStartTrialModal from 'components/announcement_bar/show_start_trial_modal/show_start_trial_modal';
import UsersLimitsAnnouncementBar from 'components/announcement_bar/users_limits_announcement_bar';
import useOpenPricingModal from 'components/common/hooks/useOpenPricingModal';
import useOpenStartTrialFormModal from 'components/common/hooks/useOpenStartTrialFormModal';
import PlanUpgradeButton from 'components/global_header/right_controls/plan_upgrade_button';
import StartTrialBtn from 'components/learn_more_trial_modal/start_trial_btn';
import NotifyAdminCTA from 'components/notify_admin_cta/notify_admin_cta';
import {OnboardingTasksName} from 'components/onboarding_tasks/constants';
import {useTasksList} from 'components/onboarding_tasks/onboarding_tasks_manager';
import StartTrialFormModal from 'components/start_trial_form_modal';
import ADLDAPUpsellBanner from 'components/user_groups_modal/ad_ldap_upsell_banner';
import UpgradeLink from 'components/widgets/links/upgrade_link';
import RestrictedIndicator from 'components/widgets/menu/menu_items/restricted_indicator';

import {act, renderHookWithContext, renderWithContext} from 'tests/react_testing_utils';
import {LicenseSkus, ModalIdentifiers} from 'utils/constants';

import type {GlobalState} from 'types/store';

import {IFL_UPSELLS} from './ifl_features';
import {IFL_UPSELL_MODALS, isIFLUpsellModal} from './ifl_upsells';

const adminId = 'admin-id';

// A Team Edition server past every upstream threshold for the automatic trial
// prompt: system admin, no licence now or before, more than 10 users, installed
// long ago, prompt never dismissed.
function state(): DeepPartial<GlobalState> {
    return {
        entities: {
            general: {
                config: {BuildEnterpriseReady: 'true', InstallationDate: '1', TelemetryId: 'x'},
                license: {IsLicensed: 'false', Cloud: 'false'},
            },
            admin: {prevTrialLicense: {IsLicensed: 'false'}, analytics: {TOTAL_USERS: 64}},
            users: {
                currentUserId: adminId,
                profiles: {[adminId]: {id: adminId, roles: 'system_admin system_user', email: 'commish@example.com'}},
                filteredStats: {total_users_count: 64},
            },
            roles: {roles: {system_admin: {permissions: [Permissions.SYSCONSOLE_WRITE_USERMANAGEMENT_USERS]}}},
            preferences: {myPreferences: {}},
            cloud: {subscription: undefined, products: {}, limits: {limits: {}, limitsLoaded: true}},
            limits: {serverLimits: {maxUsersLimit: 10, maxUsersHardLimit: 20, activeUserCount: 64}},
            usage: {teams: {active: 1, cloudArchived: 0, teamsLoaded: true}},
        },
        views: {modals: {modalState: {}}},
    };
}

describe('IFL: no upsells', () => {
    test('is off', () => {
        expect(IFL_UPSELLS).toBe(false);
    });

    test('the "Start Trial" form opener does nothing', () => {
        const {result} = renderHookWithContext(() => ({
            openTrialForm: useOpenStartTrialFormModal(),
            modals: useSelector((s: GlobalState) => s.views.modals.modalState),
        }), state());

        const onClose = jest.fn();
        act(() => result.current.openTrialForm(onClose));

        expect(result.current.modals).toEqual({});
        expect(onClose).not.toHaveBeenCalled();
    });

    test('the pricing opener does nothing', () => {
        const open = jest.spyOn(window, 'open').mockImplementation(() => null);
        const {result} = renderHookWithContext(() => useOpenPricingModal(), state());

        result.current.openPricingModal();

        expect(open).not.toHaveBeenCalled();
        open.mockRestore();
    });

    test('trial, pricing and other upsell modals never open, whoever opens them', () => {
        for (const modalId of [
            ModalIdentifiers.START_TRIAL_FORM_MODAL,
            ModalIdentifiers.LEARN_MORE_TRIAL_MODAL,
            ModalIdentifiers.TRIAL_BENEFITS_MODAL,
            ModalIdentifiers.FEATURE_RESTRICTED_MODAL,
            ModalIdentifiers.PRICING_MODAL,
            ModalIdentifiers.AIR_GAPPED_CONTACT_SALES,
        ]) {
            expect(isIFLUpsellModal(modalId)).toBe(true);
            expect(modalState({}, openModal({modalId, dialogType: StartTrialFormModal}))).toEqual({});
        }
    });

    test('other modals still open', () => {
        expect(IFL_UPSELL_MODALS.has(ModalIdentifiers.NOTIFY_CONFIRM_MODAL)).toBe(false);
        const dialogType = () => null;
        expect(modalState({}, openModal({modalId: ModalIdentifiers.USER_SETTINGS, dialogType}))).toEqual({
            [ModalIdentifiers.USER_SETTINGS]: {open: true, dialogProps: undefined, dialogType},
        });
    });

    test('the automatic trial prompt for admins opens nothing', () => {
        const {container, store} = renderWithContext(<ShowStartTrialModal/>, state());

        expect(container).toBeEmptyDOMElement();
        expect(store.getState().views.modals.modalState).toEqual({});
    });

    test('upsell components render nothing', () => {
        const purchaseText = <span>{'Purchase'}</span>;
        const notifyRequestData = {required_feature: 'x', required_plan: 'y', trial_notification: false};
        const trialBannerProps = {} as React.ComponentProps<typeof TrialBanner>;
        const featureDiscoveryProps = {} as React.ComponentProps<typeof FeatureDiscovery>;
        const components: Record<string, React.ReactElement> = {
            StartTrialFormModal: <StartTrialFormModal/>,
            StartTrialBtn: <StartTrialBtn/>,
            RestrictedIndicator: (
                <RestrictedIndicator
                    blocked={true}
                    feature='custom_user_groups'
                    minimumPlanRequiredForFeature={LicenseSkus.Professional}
                />
            ),
            UpgradeLink: <UpgradeLink/>,
            PurchaseLink: <PurchaseLink buttonTextElement={purchaseText}/>,
            ContactUsButton: <ContactUsButton/>,
            PlanUpgradeButton: <PlanUpgradeButton/>,
            NotifyAdminCTA: (
                <NotifyAdminCTA
                    ctaText='Notify admin'
                    notifyRequestData={notifyRequestData}
                />
            ),
            ADLDAPUpsellBanner: <ADLDAPUpsellBanner/>,
            UsersLimitsAnnouncementBar: <UsersLimitsAnnouncementBar userIsAdmin={true}/>,
            TrialBanner: <TrialBanner {...trialBannerProps}/>,
            FeatureDiscovery: <FeatureDiscovery {...featureDiscoveryProps}/>,
        };
        for (const [name, element] of Object.entries(components)) {
            const {container, unmount} = renderWithContext(element, state());
            expect([name, container.innerHTML]).toEqual([name, '']);
            unmount();
        }
    });

    test('the onboarding checklist has no Enterprise trial task, even for an admin', () => {
        const {result} = renderHookWithContext(() => useTasksList(), state());

        expect(result.current).not.toContain(OnboardingTasksName.START_TRIAL);
        expect(result.current).toContain(OnboardingTasksName.VISIT_SYSTEM_CONSOLE);
    });

    test('no locked "Manage User Settings" (upgrade to Enterprise) in the System Console', () => {
        expect(getShowLockedManageUserSettings(state() as GlobalState)).toBe(false);
    });

    test('the System Console has no feature discovery or Edition and License pages, and no paid-feature badges', () => {
        let discoveryPages = 0;
        for (const section of Object.values(AdminDefinition)) {
            for (const subsection of Object.values(section.subsections)) {
                expect(subsection.restrictedIndicator).toBeUndefined();
                if (subsection.isDiscovery) {
                    discoveryPages++;
                    expect(subsection.isHidden).toBe(true);
                }
            }
        }
        expect(discoveryPages).toBeGreaterThan(10);
        expect(AdminDefinition.about.subsections.license.isHidden).toBe(true);

        // Pages that work in Team Edition stay.
        expect(AdminDefinition.reporting.subsections.workspace_optimization.isHidden).not.toBe(true);
        expect(AdminDefinition.authentication.subsections.signup.isHidden).not.toBe(true);
    });
});
