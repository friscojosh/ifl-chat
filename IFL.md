# IFL Chat

IFL Chat is the International Fantasy League's chat service: a fork of Mattermost Team Edition v12.1.0 (`ifl/main`). The league site, iflgm.com, is the identity provider; chat has no sign-up of its own. The fork keeps upstream code as unchanged as possible. Every IFL change is either new code under `server/channels/app/ifl/` and `server/channels/api4/ifl.go` or a small hook marked `// IFL:` in an upstream file.

## What the fork changes

- **Sign-in through iflgm.com.** The site's sign-in is presented as a GitLab-shaped OAuth provider, so the standard GitLab option signs members in. After the site confirms a member's eligibility, the member is reactivated if needed, provisioned, and joined to the league team.
- **Login page goes straight to iflgm.com.** The web login and signup pages show the GitLab option with no GitLab icon and the label "Sign in with iflgm.com" (`GitLabButtonText` still wins when set). When it is the only sign-in method, the login page navigates to `/oauth/gitlab/login` on load and shows "Signing in with iflgm.com…". The automatic URL is built from an allowlist: only `redirect_to`, and only a relative path (`^\/([^/]|$)`, the check login.tsx uses). The decision is made once, in an effect after the session-expiry check, with the store initialized and `currentUser` resolved. It shows the button instead when the query has any other parameter (`extra`, `error`, `t`, `id`, `desktop_token`, `login_hint`, …) or a non-relative or repeated `redirect_to`; when the session expired (`wasLoggedIn`) or a user is signed in; in the desktop app or an embedded view; within two minutes of the last attempt in this tab (an OAuth refusal ends on `/error`, whose link leads back here, so it cannot loop); and after a user-initiated sign-out (`ifl_signed_out` in localStorage, set in `emitUserLoggedOutEvent`, cleared by clicking the button or by loading the app signed in). Storage fails closed: if reading localStorage or sessionStorage throws, the page shows the button; an in-memory mirror keeps marks for the page's lifetime when storage cannot be written. Rules and strings: `webapp/channels/src/components/login/ifl_signin.ts`. The mobile apps draw their own login screen and are unaffected.
- **IFL Chat branding on the signed-out pages.** The login and signup pages (and the other `HFRoute` pages) show the IFL Chat icon and name in the header instead of the Mattermost logo and "TEAM EDITION" badge, the tagline "League chat for the International Fantasy League" instead of Mattermost's, and a footer of "© <year> International Fantasy League" with a link to iflgm.com instead of Mattermost's copyright and the About, Privacy Policy, Terms and Help links. The `HFTRoute` footer (password reset, claim) gets the same copyright and link. The initial loading screen (shown on every page load) shows the IFL Chat icon with a gentle pulse instead of the Mattermost compass animation, whose svg is hidden; the background texture is unchanged. The `/error` page's signed "Back to Mattermost" links (permalink not found, cloud archived) say "Back to {SiteName}" like its other links. The favicons (default, unread and mention variants, which the signed-in app also swaps between), the PWA manifest icons, name and description, the `application-name` meta and the no-JavaScript message say IFL Chat. The tab title is the server's `TeamSettings.SiteName` (static.go replaces root.html's `<title>Mattermost</title>`, so that line stays). Strings and the header and footer: `webapp/channels/src/components/header_footer_route/ifl_branding.tsx` and `ifl_footer.tsx`. The icons are generated from `branding/ifl-chat-icon-1024.png`.
- **IFL Chat branding in the signed-in app.** The global header's top left shows the IFL Chat icon and name in place of the Mattermost logo and "TEAM EDITION" badge; it is still the product menu button, and the menu keeps its working items (System Console, Integrations, App Marketplace, About) but drops the "free unsupported edition of Mattermost" item. Team invites are gone, since members are provisioned by iflgm.com: no "Invite Members" button under Direct Messages, no "Invite people" in the team menu, the "+" menu or the View Members dialog, no "Invite team members" checklist task, and the channel intro never shows "Invite others to the workspace" (the default channel shows the favorite, header and notification buttons instead; other channels' "Add people" still adds members to the channel). The first-run tour steps over its "Invite people" step. The help menu links iflgm.com in place of Mattermost's documentation, and the team menu drops "Learn about teams" (Mattermost Academy). The client config's stock mattermost.com links (`AppDownloadLink`, the iOS and Android app links, `HelpLink`, `ReportAProblemLink`) are dropped as the config arrives, `EnableAskCommunityLink` is off and the "default" report-a-problem type (mattermost.com for an unlicensed server) is hidden, so "Download Apps", "Training resources", "Ask the community" and "Report a problem" disappear; a link an admin points anywhere else is kept (`webapp/channels/src/packages/mattermost-redux/src/utils/ifl_client_config.ts`). The checklist has no "Download the apps" task or "download our apps" link. The About dialog shows the IFL Chat icon, name and tagline, credits "Built on Mattermost <edition>, open source software" with a link to this repository at the server's `BuildHash` (the deployed commit; see License below), and links iflgm.com in place of Mattermost's terms and privacy policy; Mattermost's copyright line and open-source notice stay. English wording: the default channel intro says members join the league, other intros, the tour and checklist say league instead of team or workspace, and messages that named Mattermost (new-version bar, connection error, notification-permission notices, settings, help pages, About) say IFL Chat. These are message overrides by id in `webapp/channels/src/components/ifl/ifl_strings.ts`, loaded as the English translations, so upstream components and `en.json` are unchanged; `ifl_strings.test.ts` fails if an overridden id disappears from `en.json` or an override adds a placeholder. The switches are in `webapp/channels/src/components/ifl/ifl_features.ts`.
- **No Enterprise trial, upgrade or sales prompts.** IFL Chat is self-hosted Team Edition with nothing to buy, so nobody, admin or member, is offered a trial, an upgrade, a licence purchase, pricing or "contact sales". The trial, pricing and sales openers (`useOpenStartTrialFormModal`, `useOpenPricingModal`, `useOpenSalesLink`, the plugins' `window.openPricingModal`) do nothing, and the modals reducer refuses to open the trial, pricing, purchase, "feature restricted", "notify admin" and contact-sales modals whoever asks (`IFL_UPSELL_MODALS`). That includes upstream's automatic "Start Trial" form, which opened for a system admin of an unlicensed server with more than ten users. The upsell components render nothing: the "Start trial" button and form, the "paid feature" key badge (`RestrictedIndicator`), the upgrade, purchase and contact-sales links and buttons, the "View plans" header button, "Notify admin", the AD/LDAP banner in User Groups, the trial menu item, trial modals and banners, and the user-limit banner. The onboarding checklist has no Enterprise trial task and its completion card no "Start your free Enterprise trial". In the System Console the feature discovery pages (every `isDiscovery` page: AD/LDAP, SAML, OpenID, Groups, System Roles, Compliance, Data Retention and so on) and the Edition and License page (Team Edition's "upgrade to Enterprise" and trial) are hidden from the sidebar, search and routes, inline "try Enterprise" sections render nothing, no item shows a paid-feature badge, Workspace Optimization keeps its checks without "Start trial" or "Contact sales" buttons, and Users has no locked "Manage User Settings" or "Professional feature" Export button. Restricted features simply do not appear. Switch: `IFL_UPSELLS` in `ifl_features.ts`; helpers in `webapp/channels/src/components/ifl/ifl_upsells.tsx`; proof in `ifl_upsells.test.tsx`. Upstream test suites that cover the upsells mock `IFL_UPSELLS` on (one `// IFL:` line each) so they keep testing upstream's behaviour. The server pushes no upsell to Team Edition (its trial and upgrade notification jobs run only on Cloud and `EnableAPITriggerAdminNotifications` defaults off), but Mattermost's in-product notices, fetched from mattermost.com, can advertise paid plans: set `MM_ANNOUNCEMENTSETTINGS_ADMINNOTICESENABLED=false` and `MM_ANNOUNCEMENTSETTINGS_USERNOTICESENABLED=false` (see Configuration).
- **Panel sessions.** `POST /api/v4/ifl/session` accepts a signed, single-use panel token from the site and opens a chat session for the embedded panel (with a CSRF token).
- **Email sync.** `PUT /api/v4/ifl/users/{user_id}/email` (system admin only) lets the site's relay set a site-linked member's email. The upstream patch route cannot: chat keeps an OAuth user's old email on an untrusted update. It answers 400 for an account that does not sign in through iflgm.com and 409 `ifl.email.conflict` when another account holds the address. A panel session also brings an existing member's email and name up to date from the panel token, as an OAuth sign-in does (an email held by another account is skipped).
- **Panel WebSocket.** `GET /api/v4/ifl/websocket` is `/api/v4/websocket` for the iflgm.com panel: the session a chat cookie gives the handshake is dropped, so the panel's authentication challenge decides (browsers send chat.iflgm.com cookies with every handshake, and the stock route would ignore the challenge). Connections never resume, so each starts at sequence 0. When metrics are on, these connections are recorded as long requests in the API duration histogram, because `recordMetrics` exempts only the exact path `/api/v4/websocket` (`web/handlers.go:391`); harmless, and Team Edition has no metrics server.
- **Linked suspensions.** Banning or deactivating a user in chat is reported to iflgm.com, so a ban in chat is a ban on the site.
- **Commissioner moderation.** `provision.sh` in ifl-website's `ops/chat` sets `team_admin`'s permissions to exactly an allowlist (`delete_others_posts`, `edit_others_posts`, and since plan 8's PR B `manage_public_channel_properties`, `manage_private_channel_properties`, `delete_public_channel`, `delete_private_channel`), and moves those four channel-settings permissions from `channel_user` to `channel_admin`, so a channel's name, purpose, header and archiving belong to its creator and the commissioner, not every member; the site's relay makes each eligible commissioner, and only them, a team admin of the league team, and keeps nobody one while the role is anything else. Two fork rules (`server/channels/app/ifl_moderation.go`): the moderator's permissions (all six) apply only in channels the user belongs to, system admins exempt, where stock `SessionHasPermissionToChannel` would fall through to the team role for any channel of the team; and deleting a thread's first message while it has replies keeps them: the root stays in place as "(message deleted)" (prop `ifl_deleted_root`; text, files, props and pin removed; it can no longer be edited) instead of taking every reply with it. Only the server sets that prop: `SanitizeProps` strips it from every post a client, plugin or remote creates or updates (`server/public/model/ifl_post.go`). A kept root keeps its reactions, and it stays "(message deleted)" after its last reply is deleted until someone deletes it again. `server/channels/api4/ifl_moderation_test.go` proves the allowlist, the channel-settings move, both rules, that a client cannot set the prop, the refusals and that a demotion applies to an open session. Fork CI does not run it; run it after every upstream merge (step 4 below).
- **System messages from Goodell Bot, in league wording.** The web app shows system messages as posted by "Goodell Bot" (`post_info.system`, was "System") with the Goodell Bot avatar (`webapp/channels/src/images/goodell_bot.png`, drawn round) in place of the Mattermost logo, in the channel and in permalink previews. Team membership messages say "the league": "joined the league", "left the league", "added to the league by", "removed from the league", including the combined forms ("X and Y joined the league"). The web app renders these from the post type, so existing posts change too; the server's `api.team.*` strings in `server/i18n/en.json` (used for the stored post text) were changed to match. Channel wording is unchanged. The mobile apps render system messages themselves and still show "System", the Mattermost logo and "the team".
- **Site client.** Server-to-server calls to the site go through `server/channels/app/ifl/site_client.go` using the internal secret. Redirects are never followed.

## Hooks into upstream files

Found with `grep -rnE '(//|/\*|<!--) IFL' server webapp` (`// IFL`, `/* IFL` in JSX, `<!-- IFL` in HTML). Keep every one when merging upstream.

| Location | Purpose |
| --- | --- |
| `server/channels/api4/api.go:430` | Registers the IFL routes (`api.InitIFL()`). |
| `server/channels/api4/user.go:1704` | Linked suspension: ban in chat is a ban on iflgm.com. |
| `server/channels/api4/user.go:1844` | Linked suspension (second path). |
| `server/channels/api4/user_local.go:337` | Linked suspension for local-mode (mmctl) changes. |
| `server/channels/api4/post.go:851` | Moderation: deleting a thread's first message keeps its replies (`IFLDeletePost`). |
| `server/channels/app/authorization.go:135` | Moderation: the moderator's permissions apply only in channels the user belongs to. |
| `server/channels/app/post.go:970` | Moderation: a first message kept for its replies cannot be edited. |
| `server/public/model/post.go:641` | Moderation: `SanitizeProps` strips the deleted-root prop, so only the server sets it. |
| `server/channels/app/oauth.go:769` | `CompleteOAuth` signup action (bypasses `LoginByOAuth`): the same reactivation and provisioning. |
| `server/channels/app/oauth.go:873` | `LoginByOAuth`, after the site confirms eligibility: reactivate, provision, join the team. |
| `server/config/client.go:454` | Shows the iflgm.com sign-in as a GitLab-shaped provider. |
| `webapp/channels/src/actions/global_actions.tsx:43` | Imports the iflgm.com sign-in helper. |
| `webapp/channels/src/actions/global_actions.tsx:276` | A user-initiated sign-out marks the browser signed out, so the login page does not sign straight back in. |
| `webapp/channels/src/components/logged_in/logged_in.tsx:15` | Imports the iflgm.com sign-in helper. |
| `webapp/channels/src/components/logged_in/logged_in.tsx:72` | Signed in again: clears the signed-out mark. |
| `webapp/channels/src/components/login/login.tsx:59` | Imports the iflgm.com sign-in helper (replaces the GitLab icon import). |
| `webapp/channels/src/components/login/login.tsx:156` | Decides whether the login page goes straight to iflgm.com. |
| `webapp/channels/src/components/login/login.tsx:174` | GitLab option: no icon, "Sign in with iflgm.com" label, click clears the signed-out mark. |
| `webapp/channels/src/components/login/login.tsx:555` | Decides once (after session-expiry detection, store ready, user resolved) and navigates to iflgm.com. |
| `webapp/channels/src/components/login/login.tsx:875` | Card title "Sign in with your iflgm.com account" when iflgm.com is the only method. |
| `webapp/channels/src/components/login/login.tsx:962` | "Signing in with iflgm.com…" status in place of the form. |
| `webapp/channels/src/components/login/login.test.tsx:318` | Upstream GitLab button test: no icon in the accessible name. |
| `webapp/channels/src/components/login/login.test.tsx:772` | IFL login page tests. |
| `webapp/channels/src/components/signup/signup.tsx:40` | Imports the iflgm.com label (replaces the GitLab icon import). |
| `webapp/channels/src/components/signup/signup.tsx:165` | GitLab signup option: no icon, iflgm.com label. |
| `webapp/channels/src/components/header_footer_route/header.tsx:11` | Imports the IFL Chat header brand (replaces the Mattermost logo, license and config imports). |
| `webapp/channels/src/components/header_footer_route/header.tsx:20` | Header shows the IFL Chat icon and name; no Mattermost logo or edition badge. |
| `webapp/channels/src/components/header_footer_route/header_footer_route.tsx:14` | Loads the league footer (`ifl_footer.tsx`) instead of `footer.tsx`. |
| `webapp/channels/src/components/header_footer_template/header_footer_template.tsx:11` | Imports the IFL branding strings. |
| `webapp/channels/src/components/header_footer_template/header_footer_template.tsx:115` | Footer name IFL Chat (was Mattermost). |
| `webapp/channels/src/components/header_footer_template/header_footer_template.tsx:123` | League copyright. |
| `webapp/channels/src/components/header_footer_template/header_footer_template.tsx:126` | iflgm.com link in place of the About, Privacy Policy, Terms and Help links. |
| `webapp/channels/src/components/login/login.tsx:38` | Imports the league tagline. |
| `webapp/channels/src/components/login/login.tsx:900` | League tagline instead of `login.subtitle`. |
| `webapp/channels/src/components/signup/signup.tsx:38` | Imports the league tagline. |
| `webapp/channels/src/components/signup/signup.tsx:412` | League tagline instead of `signup_user_completed.subtitle`. |
| `webapp/channels/src/components/initial_loading_screen/initial_loading_screen_template.html:4685` | IFL Chat icon in the loading animation (HTML comment). |
| `webapp/channels/src/components/initial_loading_screen/initial_loading_screen.css:364` | Hides the Mattermost compass svg; styles and pulses the IFL Chat icon. The loaded state still ends with `LoadingAnimation__shrink` on `.LoadingAnimation`, which ends the screen. |
| `webapp/channels/src/components/error_page/error_page.tsx:71` | "Back to {siteName}" instead of "Back to Mattermost" (permalink not found). |
| `webapp/channels/src/components/error_page/error_page.tsx:83` | "Back to {siteName}" instead of "Back to Mattermost" (cloud archived). |
| `webapp/channels/src/packages/mattermost-redux/src/reducers/entities/general.ts:12` | Client config reducer: drops mattermost.com links (`iflClientConfig`, lines 17 and 20). |
| `webapp/channels/src/actions/views/root.ts:8` | Imports the IFL Chat English wording. |
| `webapp/channels/src/actions/views/root.ts:60` | English translations are the IFL Chat wording (`ifl_strings.ts`). |
| `webapp/channels/src/components/global_header/left_controls/product_branding/product_branding.tsx:17` | IFL Chat icon and name in the global header (free editions); import at line 9. |
| `webapp/channels/src/components/global_header/left_controls/switch_product_menu/switch_product_menu.tsx:143` | No edition item in the product menu. |
| `webapp/channels/src/components/global_header/center_controls/user_guide_dropdown/user_guide_dropdown.tsx:89` | Help menu: iflgm.com link in place of Mattermost's documentation; imports at lines 11 and 12. |
| `webapp/channels/src/components/about_build_modal/about_build_modal.tsx:188` | About: IFL Chat tagline and the Mattermost credit with the source link; icon (341), name (346) and iflgm.com link (395); imports at lines 15 to 18. |
| `webapp/channels/src/components/post_view/channel_intro_message/index.ts:38` | `usersLimit` 0: the channel intro never offers team invites. |
| `webapp/channels/src/components/sidebar/sidebar_category/sidebar_category.tsx:374` | No "Invite Members" button under Direct Messages; import at line 18. |
| `webapp/channels/src/components/sidebar/sidebar_header/sidebar_browse_or_add_channel_menu.tsx:209` | No "Invite people" in the "+" menu; import at line 21. |
| `webapp/channels/src/components/sidebar/sidebar_header/sidebar_team_menu.tsx:92` | No "Invite people" in the team menu; no "Learn about teams" (119); import at line 35. |
| `webapp/channels/src/components/team_members_modal/team_members_modal.tsx:179` | No "Invite People" button in View Members; import at line 15. |
| `webapp/channels/src/components/onboarding_tasks/onboarding_tasks_manager.tsx:148` | No invite or download checklist tasks; import at line 32. |
| `webapp/channels/src/components/onboarding_tasklist/onboarding_tasklist_completed.tsx:219` | No "download our apps" link; import at line 17. |
| `webapp/channels/src/components/tours/tour_manager.tsx:104` | The first-run tour steps over "Invite people"; imports at lines 14, 29 and 32, dependency at 110. |
| `webapp/channels/src/reducers/views/modals.ts:18` | Upsell modals (`IFL_UPSELL_MODALS`) never open; import at line 8. |
| `webapp/channels/src/components/common/hooks/useOpenStartTrialFormModal.ts:17` | The "Start Trial" form opener does nothing; import at line 9. |
| `webapp/channels/src/components/common/hooks/useOpenPricingModal.ts:23` | The pricing opener does nothing; import at line 6. |
| `webapp/channels/src/components/common/hooks/useOpenSalesLink.ts:45` | The contact-sales opener does nothing; import at line 11. |
| `webapp/channels/src/plugins/export.ts:57` | Plugins' `window.openPricingModal` does nothing; import at line 26. |
| `webapp/channels/src/components/start_trial_form_modal/index.tsx:357` | The "Start Trial" form renders nothing; import at line 25. |
| `webapp/channels/src/components/announcement_bar/show_start_trial_modal/show_start_trial_modal.tsx:80` | No automatic trial form for admins; import at line 16. |
| `webapp/channels/src/components/announcement_bar/show_tree_days_left_trial_modal/show_three_days_left_trial_modal.tsx:84` | No trial-ending modal; import at line 20. |
| `webapp/channels/src/components/learn_more_trial_modal/start_trial_btn.tsx:70` | No "Start trial" button; import at line 10. |
| `webapp/channels/src/components/widgets/menu/menu_items/restricted_indicator.tsx:142` | No paid-feature key badge or its trial prompt; import at line 12. |
| `webapp/channels/src/components/widgets/menu/menu_items/menu_cloud_trial.tsx:133` | No trial menu item; import at line 19. |
| `webapp/channels/src/components/widgets/links/upgrade_link.tsx:43` | No "Upgrade" link; import at line 9. |
| `webapp/channels/src/components/announcement_bar/purchase_link/purchase_link.tsx:41` | No "Purchase" link; import at line 9. |
| `webapp/channels/src/components/announcement_bar/contact_sales/contact_us.tsx:43` | No "Contact sales" button; import at line 11. |
| `webapp/channels/src/components/announcement_bar/users_limits_announcement_bar/index.tsx:166` | No user-limit banner; import at line 18. |
| `webapp/channels/src/components/global_header/right_controls/plan_upgrade_button/index.tsx:89` | No "View plans" header button; import at line 17. |
| `webapp/channels/src/components/notify_admin_cta/notify_admin_cta.tsx:108` | No "Notify admin" (to upgrade) button; import at line 12. |
| `webapp/channels/src/components/user_groups_modal/ad_ldap_upsell_banner.tsx:135` | No AD/LDAP upsell banner in User Groups; import at line 18. |
| `webapp/channels/src/components/onboarding_tasks/onboarding_tasks_manager.tsx:155` | No Enterprise trial checklist task; import at line 32. |
| `webapp/channels/src/components/onboarding_tasklist/onboarding_tasklist_completed.tsx:154` | No "Start your free Enterprise trial" on the completed checklist; import at line 17. |
| `webapp/channels/src/components/admin_console/admin_definition.tsx:6873` | System Console: feature discovery and Edition and License pages hidden, no paid-feature badges (`iflAdminDefinition`); import at line 42. |
| `webapp/channels/src/components/admin_console/feature_discovery/index.tsx:58` | Feature discovery ("try Enterprise") renders nothing; import at line 16. |
| `webapp/channels/src/components/admin_console/inline_section_feature_discovery/inline_section_feature_discovery.tsx:90` | No inline "try Enterprise" sections; import at line 10. |
| `webapp/channels/src/components/admin_console/license_settings/trial_banner/trial_banner.tsx:423` | No trial banner; import at line 17. |
| `webapp/channels/src/components/admin_console/workspace-optimization/dashboard.data.tsx:244` | Workspace Optimization: no "Start trial" or "Contact sales" buttons; import at line 22. |
| `webapp/channels/src/components/admin_console/system_users/system_users_export/index.tsx:117` | Users: no "Professional feature" Export button; import at line 23. |
| `webapp/channels/src/components/admin_console/team_channel_settings/team/details/team_profile.tsx:156` | Team details: no "View upgrade options"; import at line 18. |
| `webapp/channels/src/selectors/admin_console.tsx:92` | User details: no locked "Manage User Settings" (upgrade to Enterprise); import at line 13. |
| `webapp/channels/webpack.config.js:208` | PWA manifest name, short name and description. |
| `webapp/channels/src/root.html:12` | `application-name` meta is IFL Chat (HTML comment). |
| `webapp/channels/src/components/no_script/no_script_template.html:16` | No-JavaScript message names IFL Chat (HTML comment). |
| `webapp/channels/src/components/header_footer_route/ifl_branding.tsx:1` | New file: IFL Chat header brand and branding strings (with `ifl_branding.scss` and `ifl_branding.test.tsx`). |
| `webapp/channels/src/components/header_footer_route/ifl_footer.tsx:1` | New file: the league footer for the signed-out pages. |
| `webapp/channels/src/components/login/ifl_signin.ts:1` | New file: iflgm.com sign-in strings and redirect rules. |
| `webapp/channels/src/components/post/user_profile.tsx:155` | System message author is "Goodell Bot" (`post_info.system`). |
| `webapp/channels/src/components/post_profile_picture/post_profile_picture.tsx:11` | Imports the Goodell Bot avatar (replaces the Mattermost logo import). |
| `webapp/channels/src/components/post_profile_picture/post_profile_picture.tsx:89` | Goodell Bot avatar for system messages. |
| `webapp/channels/src/components/post_view/post_message_preview/avatar/avatar.tsx:11` | Imports the Goodell Bot avatar (replaces the Mattermost logo import). |
| `webapp/channels/src/components/post_view/post_message_preview/avatar/avatar.tsx:54` | Goodell Bot avatar for system messages in permalink previews. |
| `webapp/channels/src/components/post_markdown/system_message_helpers.tsx:136` | Team membership system messages say "the league". |
| `webapp/channels/src/components/post_view/combined_system_message/combined_system_message.tsx:115` | Combined team membership messages say "the league". |
| `webapp/channels/src/components/post_view/combined_system_message/last_users.tsx:37` | Expanded combined team membership messages say "the league". |
| `webapp/channels/src/components/ifl_goodell_bot/goodell_bot_icon.tsx:1` | New file: the Goodell Bot avatar (with `images/goodell_bot.png`). |
| `server/channels/api4/ifl.go:1` | New file: the panel session, email sync and panel WebSocket routes. |
| `server/channels/app/ifl_app.go:1` | New file: app-level glue for `server/channels/app/ifl`. |
| `server/channels/app/ifl_moderation.go:1` | New file: the moderation rules (plan 8). |
| `server/public/model/ifl_post.go:1` | New file: the deleted-root prop name (plan 8). |

New, IFL-only code: `server/channels/app/ifl/` (config, panel token, site client, actor, profile, tests), `server/channels/api4/ifl.go`, `server/channels/api4/ifl_test.go`, `server/channels/api4/ifl_moderation_test.go`, `server/channels/api4/ifl_websocket_test.go`, `server/channels/app/ifl_app.go`, `server/channels/app/ifl_moderation.go`, `server/public/model/ifl_post.go`, `server/build/Dockerfile.ifl`, `webapp/channels/src/components/login/ifl_signin.ts`, `webapp/channels/src/components/header_footer_route/ifl_branding.tsx` (with its `.scss` and test), `webapp/channels/src/components/header_footer_route/ifl_footer.tsx`, `webapp/channels/src/components/error_page/error_page_ifl.test.tsx`, `webapp/channels/src/images/ifl_chat_icon_64.png` and `_128.png`, `webapp/channels/src/components/ifl/` (`ifl_strings.ts`, `ifl_features.ts`, `ifl_upsells.tsx`, `ifl_product_branding.tsx` with its `.scss`, `ifl_about.tsx`, and tests), `webapp/channels/src/packages/mattermost-redux/src/utils/ifl_client_config.ts` (with its test), `.github/workflows/ifl-*.yml`, `tools/slack-migration/` (Slack migration tools, Python; not part of the server build), this file.

### The `en.json` exception

`server/i18n/en.json` carries nine `ifl.*` message strings (`ifl.email.*`, `ifl.panel.*` and `ifl.suspension.*`). It is the one upstream edit with no `// IFL:` marker because JSON has no comments. When merging, keep all `ifl.*` entries; merge conflicts here are usually adjacent-line additions, so keep both sides.

`webapp/channels/src/i18n/en.json` drops `login.gitlab` (the iflgm.com option no longer uses it, and upstream's `i18n-extract:check` fails on unused strings). Keep it out when merging; if an upstream change uses it again, run `npm run i18n-extract` in `webapp/channels`.

`webapp/channels/src/i18n/en.json` also drops `login.subtitle` and `signup_user_completed.subtitle` (replaced by the IFL tagline) and `error.generic.link` ("Back to Mattermost"; the error page uses `error.generic.siteLink`); keep them out when merging, as with `login.gitlab`.

Both `en.json` files also carry IFL text in upstream entries: in `server/i18n/en.json`, `api.team.join_team.post_and_forget`, `api.team.leave.left`, `api.team.add_user_to_team.added` and `api.team.remove_user_from_team.removed` say "the league"; in `webapp/channels/src/i18n/en.json`, `post_info.system` is "Goodell Bot" and the team membership messages (`api.team.*`, `combined_system_message.*_team.*`, `last_users_message.*_team.type`) say "the league". On a conflict keep ours; the webapp's source strings must match (`npm run i18n-extract:check`).

The signed-in app's English wording is not an `en.json` edit: `webapp/channels/src/components/ifl/ifl_strings.ts` overrides messages by id at runtime. If an upstream merge renames or removes an overridden id, or changes its placeholders, `ifl_strings.test.ts` fails; update the override from the new `en.json` text.

The snapshots of `sidebar_category` and `onboarding_tasklist_completed` record the missing "Invite Members" button and "download our apps" link; regenerate with jest `-u` on a conflict.

The PNGs in `webapp/channels/src/images/favicon/` are replaced with IFL Chat icons generated from `branding/ifl-chat-icon-1024.png` (same file names and sizes, so the signed-in app's favicon swaps and the PWA manifest keep working; binary files carry no marker). On a merge conflict keep ours; if upstream adds a size, generate it from the master icon with rounded corners (about 22% radius) for `favicon-*`, a red (#D24B4E) dot for `favicon-mentions-*`, a slate (#34465F) dot for `favicon-unread-*`, and full-bleed squares for `apple-touch-icon-*` and `android-chrome-*`.

Upstream test suites covering the upsells start with a `jest.mock('components/ifl/ifl_features', …IFL_UPSELLS: true)` line marked `// IFL:` (find them with `grep -rln "IFL_UPSELLS: true" webapp/channels/src`), so they keep testing upstream's behaviour; keep the line when merging. A new upstream test of an upsell that fails after a merge gets the same line.

The header_footer_template snapshots (`webapp/channels/src/components/header_footer_template/__snapshots__/`) record the league footer; regenerate with jest `-u` on a conflict.

`webapp/channels/src/components/rhs_card/__snapshots__/rhs_card.test.tsx.snap` records the Goodell Bot avatar for a system post; regenerate with jest `-u` on a conflict.

Likewise `webapp/channels/src/components/signup/__snapshots__/signup.test.tsx.snap` records the iflgm.com GitLab option (no icon, "Sign in with iflgm.com"); on a conflict, regenerate it with jest `-u` and check that only that changed.

## Configuration

All are environment variables read by `server/channels/app/ifl/config.go`.

| Variable | Meaning |
| --- | --- |
| `IFL_SESSION_SECRET` | Shared secret for panel tokens; the site's `CHAT_SESSION_SECRET`. |
| `IFL_SITE_INTERNAL_URL` | Internal base URL of the site, for example `http://10.98.0.1:8081`. |
| `IFL_INTERNAL_SECRET` | Secret for server-to-server calls; the site's `CHAT_INTERNAL_SECRET`. |
| `IFL_TEAM_NAME` | Team every member joins. |
| `IFL_SERVICE_USERNAME` | The relay's admin account. |

Server settings for the deployment (standard Mattermost environment variables, not read by IFL code):

| Variable | Meaning |
| --- | --- |
| `MM_ANNOUNCEMENTSETTINGS_ADMINNOTICESENABLED=false` | No in-product notices from mattermost.com for admins (they can advertise paid plans). |
| `MM_ANNOUNCEMENTSETTINGS_USERNOTICESENABLED=false` | No in-product notices from mattermost.com for members. |

## Build and deploy

- `server/build/Dockerfile.ifl` is upstream's `Dockerfile` with the package download replaced by a COPY of `mattermost-team-linux-amd64.tar.gz` from the build context.
- On every push to `ifl/main`, `.github/workflows/ifl-image.yml` runs the IFL tests, builds the webapp and Team Edition package, builds the image, smoke-tests `mattermost version`, and pushes `ghcr.io/friscojosh/ifl-chat:<commit sha>`.
- Local build:
  ```
  cd server && make setup-go-work
  make build-client build-linux-amd64 package-linux-amd64 BUILD_ENTERPRISE=false
  cp dist/mattermost-team-linux-amd64.tar.gz build/
  docker build -f build/Dockerfile.ifl -t ifl-chat:local build
  docker run --rm --entrypoint /mattermost/bin/mattermost ifl-chat:local version
  ```
  Do not commit the tarball.
- Deploy by pulling the `<sha>` image on CT 122 and recreating the container with the `IFL_*` variables above.
- `.github/workflows/ifl-upstream.yml` runs weekly (Monday 09:00 UTC), finds the newest upstream release not yet in `ifl/main`, trial-merges it, runs tests, builds and pushes a candidate image `ghcr.io/friscojosh/ifl-chat:candidate-<tag>`, and opens or updates an issue titled `Upstream <tag>`. It never pushes a branch.

## Upstream releases

Done on a workstation, after an `Upstream <tag>` issue appears:

1. `git fetch upstream --tags`
2. `git checkout ifl/main`
3. `git merge <tag>`; resolve any conflicts keeping every `// IFL:` hook and every `ifl.*` string in `en.json`. Take in the release's own `Dockerfile` changes by hand if relevant to `Dockerfile.ifl`.
4. `cd server && make setup-go-work && go build ./... && go test ./channels/app/ifl/`
   The route tests in `server/channels/api4/ifl_test.go` are not run by CI: upstream's API test helper needs a Postgres and a Redis on `localhost:6379`. To run them, start both (for example `docker run -d -p 127.0.0.1:55620:5432 -e POSTGRES_USER=mmuser -e POSTGRES_PASSWORD=mostest_password -e POSTGRES_DB=mattermost_test postgres:16` and `docker run -d -p 127.0.0.1:6379:6379 redis:7`), then `TEST_DATABASE_POSTGRESQL_DSN='postgres://mmuser:mostest_password@127.0.0.1:55620/mattermost_test?sslmode=disable' go test ./channels/api4/ -run '^TestIFL' -count=1` (about a minute once compiled).
5. Push `ifl/main`; CI builds the image.
6. Deploy that image to CT 122 with ifl-website's ops/chat README image-update procedure (the tunnel stays down until provision.sh has set and checked the moderator role: a new upstream permissions migration can add to team_admin, and until then the site's relay logs "team_admin is not the moderator allowlist" and keeps nobody a moderator), and run the acceptance checks (sign-in, panel session, linked suspension, a moderator delete).
7. Close the `Upstream <tag>` issue.

Merge, do not rebase: it keeps `ifl/main` linear for CI and preserves conflict resolutions across releases.

## License (AGPL)

Mattermost server code is licensed under the GNU AGPL v3 (see `LICENSE.txt`); IFL Chat is a modified version. The source of the running service is this repository at the deployed commit: the image tag is the commit SHA, so `https://github.com/friscojosh/ifl-chat/tree/<sha>` is the corresponding source for the service built from that image.
