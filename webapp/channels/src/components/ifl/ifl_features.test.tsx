// Copyright (c) 2015-present Mattermost, Inc. All Rights Reserved.
// See LICENSE.txt for license information.

// IFL: new file. The signed-in app offers no team invites, even to a user
// allowed to send them, and the first-run tour steps over its "Invite people" step.

import React from 'react';

import type {DeepPartial} from '@mattermost/types/utilities';

import {Permissions} from 'mattermost-redux/constants';

import SidebarTeamMenu from 'components/sidebar/sidebar_header/sidebar_team_menu';
import {OnboardingTourSteps, TutorialTourName} from 'components/tours/constant';
import {useTourTipManager} from 'components/tours/tour_manager';

import {act, renderHookWithContext, renderWithContext, screen, userEvent, waitFor} from 'tests/react_testing_utils';
import {TestHelper} from 'utils/test_helper';

import type {GlobalState} from 'types/store';

import {IFL_APP_DOWNLOAD_PROMPTS, IFL_MATTERMOST_LINKS, IFL_TEAM_INVITES} from './ifl_features';

jest.mock('mattermost-redux/actions/preferences', () => ({
    savePreferences: jest.fn(() => ({type: 'MOCK_SAVE_PREFERENCES'})),
}));

const {savePreferences} = jest.requireMock('mattermost-redux/actions/preferences');

const currentTeam = TestHelper.getTeamMock({id: 'team-id', name: 'ifl', display_name: 'IFL'});
const userId = 'current-user-id';

function state(step?: number): DeepPartial<GlobalState> {
    return {
        entities: {
            general: {config: {EnableGuestAccounts: 'true'}, license: {IsLicensed: 'false'}},
            teams: {
                currentTeamId: currentTeam.id,
                teams: {[currentTeam.id]: currentTeam},
                myMembers: {[currentTeam.id]: {roles: 'team_user'}},
            },
            users: {
                currentUserId: userId,
                profiles: {[userId]: {id: userId, roles: 'system_user'}},
            },
            roles: {
                roles: {
                    system_user: {permissions: []},
                    team_user: {permissions: [Permissions.ADD_USER_TO_TEAM, Permissions.INVITE_GUEST, Permissions.INVITE_USER]},
                },
            },
            preferences: {
                myPreferences: step === undefined ? {} : {
                    [`${TutorialTourName.ONBOARDING_TUTORIAL_STEP}--${userId}`]: {
                        category: TutorialTourName.ONBOARDING_TUTORIAL_STEP,
                        name: userId,
                        user_id: userId,
                        value: String(step),
                    },
                },
            },
            cloud: {subscription: {is_free_trial: 'false'}, products: {}},
            usage: {teams: {active: 1, cloudArchived: 0, teamsLoaded: true}},
        },
        plugins: {components: {MainMenu: []}},
    };
}

function savedStep(): string | undefined {
    const [, preferences] = savePreferences.mock.calls[savePreferences.mock.calls.length - 1];
    return preferences.find((p: {name: string}) => p.name === userId)?.value;
}

describe('IFL features', () => {
    beforeEach(() => {
        savePreferences.mockClear();
    });

    test('are all off', () => {
        expect(IFL_TEAM_INVITES).toBe(false);
        expect(IFL_APP_DOWNLOAD_PROMPTS).toBe(false);
        expect(IFL_MATTERMOST_LINKS).toBe(false);
    });

    test('the team menu has no "Invite people", even with permission to invite', async () => {
        renderWithContext(<SidebarTeamMenu currentTeam={currentTeam}/>, state());

        await userEvent.click(screen.getByText('IFL'));

        await waitFor(() => {
            expect(screen.getByText('View members')).toBeInTheDocument();
        });
        expect(screen.queryByText('Invite people')).not.toBeInTheDocument();
        expect(screen.queryByText('Learn about teams')).not.toBeInTheDocument();
    });

    test('the tour steps over "Invite people" going forward', () => {
        const {result} = renderHookWithContext(() => useTourTipManager(TutorialTourName.ONBOARDING_TUTORIAL_STEP), state(OnboardingTourSteps.CREATE_AND_JOIN_CHANNELS));

        act(() => result.current.handleNext({stopPropagation: jest.fn(), preventDefault: jest.fn()} as unknown as React.MouseEvent));

        expect(savedStep()).toBe(String(OnboardingTourSteps.SEND_MESSAGE));
    });

    test('the tour steps over "Invite people" going back', () => {
        const {result} = renderHookWithContext(() => useTourTipManager(TutorialTourName.ONBOARDING_TUTORIAL_STEP), state(OnboardingTourSteps.SEND_MESSAGE));

        act(() => result.current.handlePrevious({stopPropagation: jest.fn(), preventDefault: jest.fn()} as unknown as React.MouseEvent));

        expect(savedStep()).toBe(String(OnboardingTourSteps.CREATE_AND_JOIN_CHANNELS));
    });
});
