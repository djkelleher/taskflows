module.exports = {
  content: [
    "./**/*.py",
    "./**/*.js",
    "./node_modules/preline/dist/*.js",
  ],
  theme: {
    extend: {
      colors: {
        'electric-blue': '#0062FF',
        'neon-green': '#00FF66',
        'neon-red': '#FF3300',
      },
    },
  },
  plugins: [
    require('@tailwindcss/forms'),
    require('preline/plugin'),
  ],
}
