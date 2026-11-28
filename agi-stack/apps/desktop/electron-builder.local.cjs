const { buildConfiguration } = require('./scripts/desktop-package-profile.cjs');
module.exports = buildConfiguration({
  local: true,
  full: process.env.AGISTACK_DESKTOP_PROFILE === 'full',
});
