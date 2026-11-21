// Copyright (c) 2015-present Mattermost, Inc. All Rights Reserved.
// See LICENSE.txt for license information.

// IFL: new file. English wording for IFL Chat, by message id. English has no
// translation file (the webapp shows each message's defaultMessage), so these
// are loaded as the English translations (actions/views/root.ts) and win over
// the defaultMessage. That changes what members read without touching the
// upstream components or en.json. ifl_strings.test.ts checks every id still
// exists in en.json with the same placeholders, so an upstream rename fails
// the test instead of silently showing Mattermost's text again.

export const IFL_EN_STRINGS: Record<string, string> = {

    // Channel intro: the league, not the team or workspace.
    'intro_messages.default': 'Welcome to {display_name}. Post messages here that you want everyone in the league to see. Everyone automatically becomes a member of this channel when they join the league.',
    'intro_messages.readonly.default': 'Welcome to {display_name}. Messages can only be posted by admins. Everyone automatically becomes a permanent member of this channel when they join the league.',
    'intro_messages.anyMember': 'This is the start of {display_name}. Any league member can join and read this channel.',
    'intro_messages.offTopic': 'This is the start of {display_name}, a channel for conversations that aren’t about the league.',

    // Invites: members join through iflgm.com, so the "add people" picker does not offer a team invite.
    'channel_invite.no_options_message': 'No matches found',

    // First-run tour and checklist.
    'onboardingTour.ChannelsAndDirectMessagesTour.channels': 'Channels are where you can talk with the league about a topic.',
    'onboardingTour.ChannelsAndDirectMessagesTour.townSquare': 'We’ve also added the <b>{townSquare}</b> and <b>{offTopic}</b> channels for everyone in the league.',
    'onboardingTour.CreateAndJoinChannels.Description': 'Create new channels or browse available channels to see what the league is discussing. As you join channels, organize them into categories.',
    'next_steps_view.welcomeToMattermost': 'Welcome to IFL Chat',
    'onboardingTask.checklist.completed_subtitle': 'We hope IFL Chat is more familiar now.',

    // Banners, errors and settings that name the product.
    'version_bar.new': 'A new version of IFL Chat is available.',
    'channel_loader.socketError': 'Please check your connection: IFL Chat is unreachable. If the problem persists, tell a league admin.',
    'error.local_storage.title': 'Cannot Load IFL Chat',
    'error.local_storage.message': 'IFL Chat was unable to load because a setting in your browser prevents the use of its local storage features. To allow IFL Chat to load, try the following actions:',
    'activity_log.sessionsDescription': 'Sessions are created when you log in through a new browser on a device. Sessions let you use IFL Chat without having to log in again for a time period specified by the system administrator. To end the session sooner, use the \'Log Out\' button.',
    'channel_notifications.desktopNotificationsDesc': 'Available on Chrome, Edge, Firefox, and the desktop app.',
    'channel_notifications.mobileNotificationsDesc': 'Notification alerts are pushed to your mobile device when there is activity in IFL Chat.',
    'user.settings.languages.promote1': 'Select which language IFL Chat displays in the user interface.',
    'user.settings.notifications.desktopAndMobile.notificationSection.permissionDenied.message': 'You\'re missing important message and call notifications from IFL Chat. To start receiving notifications, please enable notifications for IFL Chat in your browser settings.',
    'user.settings.notifications.desktopAndMobile.notificationSection.permissionNeverGranted.message': 'You\'re missing important message and call notifications from IFL Chat. IFL Chat notifications are disabled by this browser.',
    'user.settings.notifications.desktopAndMobile.notificationSection.permissionUnsupported.message': 'You\'re missing important message and call notifications from IFL Chat. To start receiving notifications, please update to a supported browser.',
    'user.settings.notifications.desktopAndMobile.notificationSection.permissionDeniedDesktop.message': 'You\'re missing important message and call notifications from IFL Chat. To start receiving them, please enable them manually.',
    'user.settings.notifications.desktopAndMobile.notificationSection.permissionDeniedDesktop.messageDenied': 'Notifications for this IFL Chat server are blocked. To receive notifications, please enable them manually.',
    'user.settings.tokens.confirmDelete.description': 'Any integrations using this token will no longer be able to access the IFL Chat API. You cannot undo this action.',
    'apps.error.parser.no_match': '`{command}`: No matching command found.',

    // Help pages (/help/...).
    'help.commands.intro': 'You can execute commands, called slash commands, by typing into the text input box to perform operations in IFL Chat. To run a slash command, type <code>/</code> followed by a command and some arguments to perform actions.',
    'help.messaging.write.description': 'Use the text input box at the bottom of the IFL Chat interface to write a message. Press <b>ENTER</b> to send the message. Use <b>SHIFT+ENTER</b> to create a new line without sending a message.',
    'help.messaging.attach.description': 'Drag and drop files into IFL Chat, or select the Attachment icon in the text input box.',
    'help.formatting.syntax.description': 'To add syntax highlighting, type the language to be highlighted after the <code>```</code> at the beginning of the code block. IFL Chat also offers four different code themes (GitHub, Solarized Dark, Solarized Light, Monokai) that can be changed in <b>Settings > Display > Theme > Custom Theme > Center Channel Styles > Code Theme</b>.',
    'help.mentioning.username.description2': 'Type <code>@</code> to bring up a list of league members who can be mentioned. To filter the list, type the first few letters of any username, first name, last name, or nickname. The Up and Down arrow keys can then be used to scroll through entries in the list, and pressing ENTER will select which user to mention. Once selected, the username will automatically replace the full name or nickname. The following example sends a special mention notification to alice that alerts her of the channel and message where she has been mentioned. If alice is away from IFL Chat and has email notifications turned on, then she will receive an email alert of her mention along with the message text.',
    'help.attaching.supported.description': 'If you are trying to preview a media type that is not supported, the file previewer opens a standard media attachment icon. Supported media formats depend heavily on your browser and operating system. The following formats are supported by IFL Chat on most browsers:',
    'help.attaching.size.description': 'IFL Chat supports up to ten files attached per post. The default maximum file size is 100 MB (megabytes), but this can be changed by your System Admin. Image files can be a maximum size of 7680 pixels x 4320 pixels, with a maximum image resolution of 33 MP (mega pixels) or 8K resolution, and a maximum raw image file size of approximately 253 MB.',
    'help.attaching.public.description': 'Public links enable you to share file attachments with people outside IFL Chat. Open the file previewer by selecting the thumbnail of an attachment, then select <b>Get a public link</b>. Copy the link provided. When the link is shared and opened by another user, the file automatically downloads.',
    'help.attaching.previewer.description': 'IFL Chat has a built-in file previewer used to view media, download files, and to share public links. Select the thumbnail of an attached file to open it in the file previewer.',
    'help.commands.builtin.description': 'IFL Chat comes with built-in slash commands. See the <link>product documentation</link> for a list of them.',
};

export function isEnglish(locale: string): boolean {
    return locale === 'en' || locale.startsWith('en-');
}
