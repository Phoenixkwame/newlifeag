(() => {
    const root = document.querySelector('[data-slideshow]');
    if (!root) return;
    const slides = [...root.querySelectorAll('[data-slide]')];
    const controls = root.querySelector('.church-slide-controls');
    const pause = root.querySelector('[data-pause]');
    const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
    let index = 0, timer, paused = motion.matches;
    const stop = () => { clearInterval(timer); timer = null; };
    const show = (next) => {
        index = (next + slides.length) % slides.length;
        slides.forEach((slide, i) => { slide.hidden = i !== index; slide.classList.toggle('is-current', i === index); });
        root.querySelector('[data-position]').textContent = `${index + 1} / ${slides.length}`;
    };
    const start = () => {
        stop();
        pause.textContent = paused ? pause.dataset.playLabel : pause.dataset.pauseLabel;
        if (!paused && !document.hidden && !root.contains(document.activeElement)) timer = setInterval(() => show(index + 1), 8000);
    };
    const navigate = (step) => { paused = true; show(index + step); start(); };
    root.querySelector('[data-prev]').addEventListener('click', () => navigate(-1));
    root.querySelector('[data-next]').addEventListener('click', () => navigate(1));
    pause.addEventListener('click', () => { paused = !paused; start(); });
    root.addEventListener('keydown', (event) => {
        if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); navigate(event.key === 'ArrowLeft' ? -1 : 1); }
    });
    root.addEventListener('mouseenter', stop);
    root.addEventListener('mouseleave', start);
    root.addEventListener('focusin', stop);
    root.addEventListener('focusout', () => setTimeout(start, 0));
    document.addEventListener('visibilitychange', start);
    motion.addEventListener('change', () => { if (motion.matches) { paused = true; start(); } });
    show(0); controls.hidden = false; start();
})();
