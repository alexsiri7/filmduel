export default {
  test: {
    globals: false,
    environment: 'node',
    passWithNoTests: true,
    exclude: [
      'node_modules',
      'frontend',
      'dist',
      '.idea',
      '.git',
      '.cache',
    ],
  },
};
