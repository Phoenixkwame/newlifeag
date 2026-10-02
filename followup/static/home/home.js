/* Progressive enhancements: all destinations and content work without this file. */
(() => {
    'use strict';
    const root = document.querySelector('.home-page');
    if (!root) return;
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    const mobileMenu = document.querySelector('.home-mobile-menu');
    if (mobileMenu) {
        mobileMenu.addEventListener('keydown', (event) => {
            if (event.key !== 'Escape' || !mobileMenu.open) return;
            event.preventDefault();
            mobileMenu.open = false;
            mobileMenu.querySelector('summary').focus();
        });
        mobileMenu.addEventListener('click', (event) => {
            if (event.target.closest('a')) mobileMenu.open = false;
        });
        document.addEventListener('click', (event) => {
            if (mobileMenu.open && !mobileMenu.contains(event.target)) mobileMenu.open = false;
        });
    }
    const photoLinks = root.querySelectorAll('[data-photo-open]');
    const photoDialog = root.querySelector('[data-photo-dialog]');
    if (photoLinks.length && photoDialog && typeof photoDialog.showModal === 'function') {
        const photoImage = photoDialog.querySelector('img');
        const photoTitle = photoDialog.querySelector('h2');
        const defaultTitle = photoTitle.textContent;
        let activePhotoLink;
        photoLinks.forEach((photoLink) => {
            photoLink.setAttribute('aria-haspopup', 'dialog');
            photoLink.addEventListener('click', (event) => {
                if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button > 0) return;
                event.preventDefault();
                activePhotoLink = photoLink;
                photoImage.src = photoLink.href;
                photoImage.alt = photoLink.dataset.photoAlt || photoLink.querySelector('img')?.alt || '';
                // Each supplied portrait keeps its own aspect ratio.
                photoImage.removeAttribute('width');
                photoImage.removeAttribute('height');
                photoTitle.textContent = photoLink.dataset.photoTitle || defaultTitle;
                photoDialog.showModal();
            });
        });
        photoDialog.addEventListener('close', () => activePhotoLink?.focus());
        photoDialog.addEventListener('click', (event) => {
            if (event.target !== photoDialog) return;
            const bounds = photoDialog.getBoundingClientRect();
            if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) photoDialog.close();
        });
    }

    const experience = root.querySelector('[data-experience]');
    if (experience) {
        const tablist = experience.querySelector('[role="tablist"]');
        const tabs = [...experience.querySelectorAll('[role="tab"]')];
        const selectTab = (selected) => {
            tabs.forEach((tab) => {
                const active = tab === selected;
                tab.setAttribute('aria-selected', String(active));
                tab.tabIndex = active ? 0 : -1;
                const panel = document.getElementById(tab.getAttribute('aria-controls'));
                panel.hidden = !active;
                panel.setAttribute('role', 'tabpanel');
                panel.setAttribute('aria-labelledby', tab.id);
                panel.tabIndex = 0;
            });
        };
        tabs.forEach((tab, index) => {
            tab.addEventListener('click', () => selectTab(tab));
            tab.addEventListener('keydown', (event) => {
                let next;
                if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
                if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length;
                if (event.key === 'Home') next = 0;
                if (event.key === 'End') next = tabs.length - 1;
                if (next === undefined) return;
                event.preventDefault();
                selectTab(tabs[next]);
                tabs[next].focus();
            });
        });
        selectTab(tabs[0]);
        tablist.hidden = false;
    }

    const countdown = root.querySelector('[data-countdown]');
    if (countdown) {
        const target = Date.parse(countdown.dataset.countdown);
        let timer;
        const update = () => {
            const seconds = Math.max(0, Math.floor((target - Date.now()) / 1000));
            if (!Number.isFinite(target) || seconds === 0) {
                countdown.hidden = true;
                if (timer) window.clearInterval(timer);
                return false;
            }
            const values = { days: Math.floor(seconds / 86400), hours: Math.floor(seconds / 3600) % 24, minutes: Math.floor(seconds / 60) % 60, seconds: seconds % 60 };
            Object.entries(values).forEach(([unit, value]) => {
                countdown.querySelector(`[data-unit="${unit}"]`).textContent = String(value).padStart(2, '0');
            });
            countdown.hidden = false;
            return true;
        };
        if (update()) timer = window.setInterval(update, 1000);
    }

    const strip = root.querySelector('#home-flyers');
    const controls = root.querySelector('.home-slider-controls');
    if (strip && controls) {
        const previous = controls.querySelector('[data-slide="-1"]');
        const next = controls.querySelector('[data-slide="1"]');
        const updateControls = () => {
            const overflow = strip.scrollWidth - strip.clientWidth;
            controls.hidden = overflow <= 2;
            previous.disabled = strip.scrollLeft <= 2;
            next.disabled = strip.scrollLeft >= overflow - 2;
        };
        controls.querySelectorAll('[data-slide]').forEach((button) => {
            button.addEventListener('click', () => {
                strip.scrollBy({ left: Number(button.dataset.slide) * strip.clientWidth, behavior: reducedMotion.matches ? 'instant' : 'smooth' });
            });
        });
        strip.addEventListener('scroll', updateControls, { passive: true });
        window.addEventListener('resize', updateControls);
        updateControls();
    }

    if ('IntersectionObserver' in window && !reducedMotion.matches) {
        const observer = new IntersectionObserver((entries) => {
            entries.forEach((entry) => {
                if (!entry.isIntersecting) return;
                entry.target.classList.add('is-revealed');
                observer.unobserve(entry.target);
            });
        }, { threshold: 0.08 });
        root.querySelectorAll('.home-section').forEach((section) => observer.observe(section));
    }
})();
