/**
 * SmartStudy Frontend JavaScript
 */

const SmartStudy = (() => {
    const THEME_KEY = "smartstudy_theme";
    const SOUND_KEY = "smartstudy_sound";

    function initTheme() {
        const savedTheme = localStorage.getItem(THEME_KEY) || "light";
        setTheme(savedTheme);

        const toggleBtn = document.getElementById("themeToggleBtn");
        if (toggleBtn) {
            toggleBtn.addEventListener("click", () => {
                const current = document.documentElement.getAttribute("data-bs-theme") || "light";
                setTheme(current === "dark" ? "light" : "dark");
            });
        }
    }

    function setTheme(theme) {
        document.documentElement.setAttribute("data-bs-theme", theme);
        localStorage.setItem(THEME_KEY, theme);
        const iconEl = document.getElementById("themeToggleIcon");
        if (iconEl) {
            iconEl.className = theme === "dark" ? "bi bi-sun-fill text-warning" : "bi bi-moon-stars-fill";
        }
    }

    function isSoundEnabled() {
        return localStorage.getItem(SOUND_KEY) !== "off";
    }

    function initSoundToggle() {
        const soundBtn = document.getElementById("soundToggleBtn");
        const updateIcon = () => {
            if (soundBtn) {
                soundBtn.innerHTML = isSoundEnabled()
                    ? '<i class="bi bi-volume-up-fill"></i>'
                    : '<i class="bi bi-volume-mute-fill text-muted"></i>';
                soundBtn.title = isSoundEnabled() ? "Âm thanh: Đang bật" : "Âm thanh: Đang tắt";
            }
        };
        updateIcon();
        if (soundBtn) {
            soundBtn.addEventListener("click", () => {
                localStorage.setItem(SOUND_KEY, isSoundEnabled() ? "off" : "on");
                updateIcon();
            });
        }
    }

    function playSound(type) {
        if (!isSoundEnabled()) return;
        try {
            const AudioCtx = window.AudioContext || window.webkitAudioContext;
            if (!AudioCtx) return;
            const ctx = new AudioCtx();
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.connect(gain);
            gain.connect(ctx.destination);

            if (type === "correct") {
                osc.type = "sine";
                osc.frequency.setValueAtTime(523.25, ctx.currentTime);
                osc.frequency.setValueAtTime(659.25, ctx.currentTime + 0.09);
                osc.frequency.setValueAtTime(783.99, ctx.currentTime + 0.18);
                gain.gain.setValueAtTime(0.15, ctx.currentTime);
                gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.35);
                osc.start();
                osc.stop(ctx.currentTime + 0.35);
            } else if (type === "wrong") {
                osc.type = "triangle";
                osc.frequency.setValueAtTime(300, ctx.currentTime);
                osc.frequency.setValueAtTime(210, ctx.currentTime + 0.12);
                gain.gain.setValueAtTime(0.18, ctx.currentTime);
                gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.32);
                osc.start();
                osc.stop(ctx.currentTime + 0.32);
            }
        } catch (err) {}
    }

    function launchConfetti() {
        const colors = ["#4f46e5", "#10b981", "#f59e0b", "#ec4899", "#06b6d4", "#ef4444"];
        for (let i = 0; i < 70; i++) {
            const piece = document.createElement("div");
            piece.className = "confetti-piece";
            piece.style.left = Math.random() * 100 + "vw";
            piece.style.backgroundColor = colors[Math.floor(Math.random() * colors.length)];
            piece.style.animationDuration = (Math.random() * 2 + 2) + "s";
            piece.style.animationDelay = (Math.random() * 0.5) + "s";
            document.body.appendChild(piece);
            setTimeout(() => piece.remove(), 4200);
        }
    }

    document.addEventListener("DOMContentLoaded", () => {
        initTheme();
        initSoundToggle();
    });

    return {
        playSound,
        launchConfetti,
        isSoundEnabled
    };
})();
