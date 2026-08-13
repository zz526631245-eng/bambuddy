import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'com.bambuddy.mobile',
  appName: 'BambuddyMobile',
  webDir: '../static',
  android: {
    // Bambuddy is commonly deployed on a trusted local network without TLS.
    // The bundled WebView itself is served from https://localhost, so enable
    // its HTTP requests to that operator-configured LAN server.
    allowMixedContent: true,
  },
};

export default config;
