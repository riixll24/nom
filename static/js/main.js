(function () {
    'use strict';

    function onReady(fn) {
        if (document.readyState !== 'loading') fn();
        else document.addEventListener('DOMContentLoaded', fn);
    }

    // 1) Reveal-on-scroll: add .is-visible to .reveal elements when they enter viewport
    function initReveal() {
        var targets = document.querySelectorAll('.reveal, .opp-card, .step-card, .testimonial-card, .stat-card');
        if (!targets.length) return;
        targets.forEach(function (el) { el.classList.add('reveal'); });

        if (!('IntersectionObserver' in window)) {
            targets.forEach(function (el) { el.classList.add('is-visible'); });
            return;
        }
        var io = new IntersectionObserver(function (entries) {
            entries.forEach(function (e) {
                if (e.isIntersecting) {
                    e.target.classList.add('is-visible');
                    io.unobserve(e.target);
                }
            });
        }, { threshold: 0.12 });
        targets.forEach(function (el) { io.observe(el); });
    }

    // 2) Auto-dismiss flash messages after 5s (click to dismiss immediately)
    function initFlash() {
        var flashes = document.querySelectorAll('.flash');
        flashes.forEach(function (el) {
            el.style.cursor = 'pointer';
            el.title = 'اضغط للإغلاق';
            var dismiss = function () {
                el.style.transition = 'opacity .4s ease, transform .4s ease';
                el.style.opacity = '0';
                el.style.transform = 'translateY(-8px)';
                setTimeout(function () { el.remove(); }, 420);
            };
            el.addEventListener('click', dismiss);
            setTimeout(dismiss, 5000);
        });
    }

    // 3) Mobile nav toggle (adds a burger button when nav-links exists)
    function initMobileNav() {
        var navbar = document.querySelector('.navbar');
        var links = document.querySelector('.nav-links');
        if (!navbar || !links) return;
        if (navbar.querySelector('.nav-toggle')) return;

        var btn = document.createElement('button');
        btn.className = 'nav-toggle';
        btn.setAttribute('aria-label', 'القائمة');
        btn.setAttribute('aria-expanded', 'false');
        btn.innerHTML = '<span></span><span></span><span></span>';
        navbar.appendChild(btn);

        btn.addEventListener('click', function () {
            var open = links.classList.toggle('nav-open');
            btn.setAttribute('aria-expanded', open ? 'true' : 'false');
            btn.classList.toggle('is-open', open);
        });
    }

    // 4) Smooth anchor scrolling
    function initSmoothAnchors() {
        document.querySelectorAll('a[href^="#"]').forEach(function (a) {
            a.addEventListener('click', function (ev) {
                var id = a.getAttribute('href');
                if (!id || id === '#') return;
                var target = document.querySelector(id);
                if (!target) return;
                ev.preventDefault();
                target.scrollIntoView({ behavior: 'smooth', block: 'start' });
            });
        });
    }

    // 5) Password visibility toggle on any <input type="password">
    function initPasswordToggles() {
        document.querySelectorAll('input[type="password"]').forEach(function (input) {
            if (input.dataset.toggleAttached) return;
            input.dataset.toggleAttached = '1';

            var wrap = document.createElement('div');
            wrap.className = 'pw-wrap';
            input.parentNode.insertBefore(wrap, input);
            wrap.appendChild(input);

            var btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'pw-toggle';
            btn.setAttribute('aria-label', 'إظهار/إخفاء كلمة المرور');
            btn.textContent = '👁';
            wrap.appendChild(btn);

            btn.addEventListener('click', function () {
                var showing = input.type === 'text';
                input.type = showing ? 'password' : 'text';
                btn.textContent = showing ? '👁' : '🙈';
            });
        });
    }

    // 6) Prevent double-submit on forms; show "...جاري" on the submit button
    function initFormGuard() {
        document.querySelectorAll('form').forEach(function (form) {
            form.addEventListener('submit', function () {
                var btn = form.querySelector('button[type="submit"], input[type="submit"]');
                if (!btn || btn.dataset.noGuard) return;
                if (btn.disabled) return;
                btn.dataset.orig = btn.textContent;
                btn.disabled = true;
                btn.classList.add('is-loading');
                var txt = btn.textContent;
                btn.textContent = '⏳ جاري المعالجة...';
                // Safety: re-enable after 15s in case navigation doesn't happen
                setTimeout(function () {
                    btn.disabled = false;
                    btn.classList.remove('is-loading');
                    btn.textContent = txt;
                }, 15000);
            });
        });
    }

    // 7) Image preview helper — any <input type="file" data-preview="#id"> fills that <img>
    function initFilePreview() {
        document.querySelectorAll('input[type="file"][data-preview]').forEach(function (input) {
            var sel = input.getAttribute('data-preview');
            var img = document.querySelector(sel);
            if (!img) return;
            input.addEventListener('change', function () {
                var f = input.files && input.files[0];
                if (!f) return;
                var r = new FileReader();
                r.onload = function (e) {
                    img.src = e.target.result;
                    img.style.display = 'block';
                };
                r.readAsDataURL(f);
            });
        });
    }

    // 8) Hero parallax — subtle background shift on scroll
    function initHeroParallax() {
        var bg = document.querySelector('.hero-bg');
        if (!bg) return;
        if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
        var ticking = false;
        function update() {
            var y = window.scrollY || window.pageYOffset;
            bg.style.transform = 'translateY(' + (y * 0.25) + 'px)';
            ticking = false;
        }
        window.addEventListener('scroll', function () {
            if (!ticking) {
                window.requestAnimationFrame(update);
                ticking = true;
            }
        }, { passive: true });
    }

    // 9) Navbar shrink/shadow on scroll
    function initNavbarScroll() {
        var nav = document.querySelector('.navbar');
        if (!nav) return;
        function update() {
            if ((window.scrollY || window.pageYOffset) > 30) nav.classList.add('scrolled');
            else nav.classList.remove('scrolled');
        }
        update();
        window.addEventListener('scroll', update, { passive: true });
    }

    // 10) Magnetic tilt on cards — small pointer-tracking tilt
    function initCardTilt() {
        if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
        if (window.matchMedia('(pointer: coarse)').matches) return;
        var cards = document.querySelectorAll('.opp-card, .step-card, .testimonial-card');
        cards.forEach(function (card) {
            card.addEventListener('mousemove', function (e) {
                var r = card.getBoundingClientRect();
                var px = (e.clientX - r.left) / r.width - 0.5;
                var py = (e.clientY - r.top) / r.height - 0.5;
                card.style.transform = 'translateY(-6px) rotateX(' + (-py * 4) + 'deg) rotateY(' + (px * 4) + 'deg)';
            });
            card.addEventListener('mouseleave', function () {
                card.style.transform = '';
            });
        });
    }

    // 11) Ripple click on .btn
    function initRipple() {
        document.addEventListener('click', function (e) {
            var btn = e.target.closest('.btn');
            if (!btn) return;
            var r = btn.getBoundingClientRect();
            var ripple = document.createElement('span');
            ripple.className = 'btn-ripple';
            var size = Math.max(r.width, r.height);
            ripple.style.width = ripple.style.height = size + 'px';
            ripple.style.left = (e.clientX - r.left - size / 2) + 'px';
            ripple.style.top = (e.clientY - r.top - size / 2) + 'px';
            btn.appendChild(ripple);
            setTimeout(function () { ripple.remove(); }, 650);
        });
    }

    onReady(function () {
        initReveal();
        initFlash();
        initMobileNav();
        initSmoothAnchors();
        initPasswordToggles();
        initFormGuard();
        initFilePreview();
        initHeroParallax();
        initNavbarScroll();
        initCardTilt();
        initRipple();
    });
})();
