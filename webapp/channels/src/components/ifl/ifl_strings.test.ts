// Copyright (c) 2015-present Mattermost, Inc. All Rights Reserved.
// See LICENSE.txt for license information.

// IFL: new file. Tests for the IFL Chat English wording.

import fs from 'fs';
import path from 'path';

import {loadTranslations} from 'actions/views/root';

import {ActionTypes} from 'utils/constants';

import {IFL_EN_STRINGS, isEnglish} from './ifl_strings';

// Read from disk: jest maps i18n JSON imports to a mock.
const messages: Record<string, string | {defaultMessage: string}> = JSON.parse(fs.readFileSync(path.join(__dirname, '../../i18n/en.json'), 'utf8'));

function defaultMessage(id: string): string | undefined {
    const entry = messages[id];
    return typeof entry === 'string' ? entry : entry?.defaultMessage;
}

// ICU arguments ({name}) and rich-text tags (<b>) a message needs its values for.
function placeholders(message: string): string[] {
    const found = new Set<string>();
    for (const match of message.matchAll(/\{\s*([A-Za-z0-9_]+)/g)) {
        found.add(`{${match[1]}}`);
    }
    for (const match of message.matchAll(/<\/?([A-Za-z0-9_]+)>/g)) {
        found.add(`<${match[1]}>`);
    }
    return [...found].sort();
}

describe('IFL_EN_STRINGS', () => {
    // An override may leave out a placeholder (its value is then unused) but
    // never add one the component does not supply.
    test.each(Object.keys(IFL_EN_STRINGS))('%s still exists upstream with no new placeholders', (id) => {
        const upstream = defaultMessage(id);
        expect(upstream).toBeDefined();
        expect(placeholders(upstream!)).toEqual(expect.arrayContaining(placeholders(IFL_EN_STRINGS[id])));
        expect(IFL_EN_STRINGS[id]).not.toEqual(upstream);
    });

    test('no override names Mattermost', () => {
        const naming = Object.keys(IFL_EN_STRINGS).filter((id) => IFL_EN_STRINGS[id].includes('Mattermost'));
        expect(naming).toEqual([]);
    });

    test('the default channel intro says the league', () => {
        expect(IFL_EN_STRINGS['intro_messages.default']).toContain('when they join the league.');
    });

    test('isEnglish', () => {
        expect(isEnglish('en')).toBe(true);
        expect(isEnglish('en-AU')).toBe(true);
        expect(isEnglish('es')).toBe(false);
        expect(isEnglish('de')).toBe(false);
    });

    test('loadTranslations uses them as the English translations', async () => {
        const dispatch = jest.fn();
        await loadTranslations('en', '')(dispatch, jest.fn(), undefined);

        expect(dispatch).toHaveBeenCalledWith({
            type: ActionTypes.RECEIVED_TRANSLATIONS,
            data: {locale: 'en', translations: expect.objectContaining(IFL_EN_STRINGS)},
        });
    });
});
