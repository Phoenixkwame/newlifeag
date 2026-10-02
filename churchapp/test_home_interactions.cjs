// Run with: node --test churchapp/test_home_interactions.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../followup/static/home/home.js'), 'utf8');

function element(attributes = {}) {
    return {
        attributes, hidden: true, dataset: {}, handlers: {},
        setAttribute(key, value) { this.attributes[key] = value; },
        getAttribute(key) { return this.attributes[key]; },
        addEventListener(key, handler) { this.handlers[key] = handler; },
        focus() { this.focused = true; },
    };
}
function run(selectors, panels = {}, now = Date.parse('2026-09-28T12:00:00Z')) {
    const state = { timers: [], cleared: [], documentHandlers: {} };
    const window = {
        matchMedia: () => ({ matches: true }),
        setInterval: (fn) => { state.timers.push(fn); return state.timers.length; },
        clearInterval: (id) => state.cleared.push(id),
        addEventListener() {},
    };
    const root = { querySelector: (key) => selectors[key] || null };
    vm.runInNewContext(source, {
        window, document: {
            querySelector: (key) => key === '.home-page' ? root : selectors[key] || null,
            getElementById: (id) => panels[id],
            addEventListener: (key, handler) => { state.documentHandlers[key] = handler; },
        },
        Date: { parse: Date.parse, now: () => now },
    });
    return state;
}

test('visit/online tabs update visibility, ARIA state, and keyboard focus', () => {
    const tabs = ['visit', 'online'].map((name) => Object.assign(element({ 'aria-controls': name }), { id: `${name}-tab` }));
    const tablist = element();
    const panels = { visit: element(), online: element() };
    const experience = { querySelector: () => tablist, querySelectorAll: () => tabs };
    run({ '[data-experience]': experience }, panels);
    assert.equal(tablist.hidden, false);
    assert.equal(panels.visit.hidden, false);
    assert.equal(panels.online.hidden, true);
    tabs[0].handlers.keydown({ key: 'ArrowRight', preventDefault() {} });
    assert.equal(panels.visit.hidden, true);
    assert.equal(panels.online.hidden, false);
    assert.equal(tabs[1].attributes['aria-selected'], 'true');
    assert.equal(tabs[1].focused, true);
    tabs[1].handlers.keydown({ key: 'Home', preventDefault() {} });
    assert.equal(panels.visit.hidden, false);
    assert.equal(tabs[0].tabIndex, 0);
    assert.equal(tabs[1].tabIndex, -1);
});

function countdown(target) {
    const node = element();
    node.dataset.countdown = target;
    node.units = Object.fromEntries(['days', 'hours', 'minutes', 'seconds'].map((key) => [key, element()]));
    node.querySelector = (selector) => node.units[selector.match(/"(.*?)"/)[1]];
    return node;
}
test('countdown uses the timestamp offset and separates days/hours/minutes/seconds', () => {
    const node = countdown('2026-09-29T15:02:03+02:00');
    const state = run({ '[data-countdown]': node });
    assert.equal(node.hidden, false);
    assert.deepEqual(Object.values(node.units).map((unit) => unit.textContent), ['01', '01', '02', '03']);
    assert.equal(state.timers.length, 1);
});
test('expired or invalid dates never display a misleading countdown', () => {
    for (const value of ['invalid', '2026-09-27T12:00:00Z']) {
        const node = countdown(value);
        const state = run({ '[data-countdown]': node });
        assert.equal(node.hidden, true);
        assert.equal(state.timers.length, 0);
    }
});
test('flyer controls respect scroll boundaries and reduced motion', () => {
    const previous = element(); previous.dataset.slide = '-1';
    const next = element(); next.dataset.slide = '1';
    const controls = element();
    controls.querySelector = (key) => key.includes('-1') ? previous : next;
    controls.querySelectorAll = () => [previous, next];
    const strip = Object.assign(element(), { scrollWidth: 1200, clientWidth: 400, scrollLeft: 0 });
    strip.scrollBy = (options) => { strip.lastScroll = options; };
    run({ '#home-flyers': strip, '.home-slider-controls': controls });
    assert.equal(previous.disabled, true);
    assert.equal(next.disabled, false);
    next.handlers.click();
    assert.equal(strip.lastScroll.left, 400);
    assert.equal(strip.lastScroll.behavior, 'instant');
    strip.scrollLeft = 800;
    strip.handlers.scroll();
    assert.equal(next.disabled, true);
    strip.scrollWidth = 400;
    strip.handlers.scroll();
    assert.equal(controls.hidden, true);
});

test('photo viewer preserves modified links and restores focus after closing', () => {
    const link = element();
    const dialog = element();
    dialog.showModal = () => { dialog.open = true; };
    dialog.close = () => { dialog.open = false; dialog.handlers.close(); };
    dialog.getBoundingClientRect = () => ({ left: 10, right: 200, top: 10, bottom: 200 });
    run({ '[data-photo-open]': link, '[data-photo-dialog]': dialog });
    let prevented = false;
    link.handlers.click({ ctrlKey: true, preventDefault() { prevented = true; } });
    assert.equal(prevented, false);
    assert.equal(dialog.open, undefined);
    link.handlers.click({ button: 0, preventDefault() { prevented = true; } });
    assert.equal(prevented, true);
    assert.equal(dialog.open, true);
    dialog.handlers.click({ target: dialog, clientX: 50, clientY: 50 });
    assert.equal(dialog.open, true);
    dialog.handlers.click({ target: dialog, clientX: 0, clientY: 0 });
    assert.equal(dialog.open, false);
    assert.equal(link.focused, true);
});

test('photo link remains a normal image link without dialog support', () => {
    const link = element();
    run({ '[data-photo-open]': link, '[data-photo-dialog]': element() });
    assert.equal(link.handlers.click, undefined);
    assert.equal(link.attributes['aria-haspopup'], undefined);
});

test('mobile menu dismisses with Escape, navigation, and outside clicks', () => {
    const menu = element();
    const summary = element();
    menu.querySelector = () => summary;
    menu.contains = (target) => target === summary;
    const state = run({ '.home-mobile-menu': menu });
    menu.open = true;
    let prevented = false;
    menu.handlers.keydown({ key: 'Escape', preventDefault() { prevented = true; } });
    assert.equal(menu.open, false);
    assert.equal(summary.focused, true);
    assert.equal(prevented, true);
    menu.open = true;
    state.documentHandlers.click({ target: summary });
    assert.equal(menu.open, true);
    state.documentHandlers.click({ target: {} });
    assert.equal(menu.open, false);
    menu.open = true;
    menu.handlers.click({ target: { closest: () => ({}) } });
    assert.equal(menu.open, false);
});
