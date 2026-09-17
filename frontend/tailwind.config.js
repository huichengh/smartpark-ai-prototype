/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // 深色科技主题背景层
        nav: {
          deep: '#07111F',
          base: '#0A1628',
          panel: '#0D1B2A',
          raised: '#101D2F',
        },
        // 主品牌色 · 科技蓝
        brand: {
          50: '#E8F3FF',
          100: '#C7E1FF',
          300: '#7FB8FF',
          400: '#4D9AFF',
          500: '#2F80ED',
          600: '#1E68D0',
          glow: '#00D4FF',
        },
        // AI 辅助 · 蓝紫
        ai: {
          DEFAULT: '#7B61FF',
          light: '#A48CFF',
          glow: '#8B7CFF',
          deep: '#5B45D6',
        },
        state: {
          ok: '#22C55E',
          info: '#2F80ED',
          warn: '#FACC15',
          risk: '#F97316',
          danger: '#EF4444',
          muted: '#64748B',
        },
      },
      fontFamily: {
        sans: ['Inter', 'HarmonyOS Sans SC', 'PingFang SC', 'Microsoft YaHei', 'system-ui', 'sans-serif'],
        num: ['Inter', 'DIN Alternate', 'Roboto Mono', 'ui-monospace', 'monospace'],
      },
      fontSize: {
        kpi: ['34px', { lineHeight: '1.1', letterSpacing: '-0.02em' }],
        'kpi-lg': ['40px', { lineHeight: '1.05', letterSpacing: '-0.02em' }],
        'kpi-sm': ['26px', { lineHeight: '1.15', letterSpacing: '-0.01em' }],
      },
      borderRadius: {
        card: '16px',
        panel: '20px',
      },
      boxShadow: {
        glass: '0 8px 32px rgba(0,0,0,0.25), inset 0 1px 0 rgba(255,255,255,0.05)',
        'glass-hover': '0 14px 44px rgba(0,0,0,0.32), inset 0 1px 0 rgba(255,255,255,0.08)',
        'glow-brand': '0 0 0 1px rgba(47,128,237,0.35), 0 8px 28px rgba(47,128,237,0.18)',
        'glow-ai': '0 0 0 1px rgba(123,97,255,0.4), 0 8px 28px rgba(123,97,255,0.2)',
        'glow-danger': '0 0 0 1px rgba(239,68,68,0.4), 0 0 24px rgba(239,68,68,0.22)',
        inset: 'inset 0 1px 0 rgba(255,255,255,0.05)',
      },
      backgroundImage: {
        'brand-grad': 'linear-gradient(135deg, #2F80ED 0%, #00C6FF 100%)',
        'ai-grad': 'linear-gradient(135deg, #7B61FF 0%, #2F80ED 100%)',
        'panel-grad': 'linear-gradient(160deg, rgba(19,38,64,0.72) 0%, rgba(11,24,42,0.72) 100%)',
        'grid-fade': 'linear-gradient(90deg, rgba(80,180,255,0.06) 1px, transparent 1px), linear-gradient(0deg, rgba(80,180,255,0.06) 1px, transparent 1px)',
      },
      keyframes: {
        fadeUp: { '0%': { opacity: '0', transform: 'translateY(8px)' }, '100%': { opacity: '1', transform: 'translateY(0)' } },
        pulseSoft: { '0%,100%': { opacity: '1' }, '50%': { opacity: '0.55' } },
        shimmer: { '0%': { backgroundPosition: '-200% 0' }, '100%': { backgroundPosition: '200% 0' } },
        flow: { '0%': { strokeDashoffset: '60' }, '100%': { strokeDashoffset: '0' } },
      },
      animation: {
        'fade-up': 'fadeUp 0.24s ease-out both',
        'pulse-soft': 'pulseSoft 2.2s ease-in-out infinite',
        shimmer: 'shimmer 2.4s linear infinite',
        flow: 'flow 2s linear infinite',
      },
    },
  },
  plugins: [],
}
