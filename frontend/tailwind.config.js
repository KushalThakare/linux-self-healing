/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        canvas: '#F9F9F8',
        surface: '#FFFFFF',
        'surface-subtle': '#F4F4F2',
        border: '#E5E5E3',
        'border-strong': '#D4D4D0',
        charcoal: {
          DEFAULT: '#1C1C1A',
          secondary: '#52524E',
          muted: '#737370',
          subtle: '#A1A19D',
        },
        accent: {
          DEFAULT: '#1D4ED8',
          hover: '#1E40AF',
          subtle: '#EFF6FF',
          border: '#BFDBFE',
        },
        status: {
          success: '#15803D',
          'success-bg': '#F0FDF4',
          'success-border': '#BBF7D0',
          failed: '#B91C1C',
          'failed-bg': '#FEF2F2',
          'failed-border': '#FECACA',
          rejected: '#B45309',
          'rejected-bg': '#FFFBEB',
          'rejected-border': '#FDE68A',
          progress: '#0369A1',
          'progress-bg': '#F0F9FF',
          'progress-border': '#BAE6FD',
        },
      },
      fontFamily: {
        sans: ['"Plus Jakarta Sans"', 'system-ui', '-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'Roboto', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'Monaco', 'Consolas', 'monospace'],
      },
      borderRadius: {
        DEFAULT: '4px',
        sm: '3px',
        md: '6px',
        lg: '8px',
      },
      letterSpacing: {
        tightest: '-0.03em',
        tighter: '-0.02em',
      },
    },
  },
  plugins: [],
};
