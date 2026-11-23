# Mobile App Configuration & Build Guide

**Last Updated**: 2026-11-19
**Status**: ✅ Active & Verified

---

## Overview

The Nexa mobile application is built using Capacitor with Android and iOS native wrappers around the React frontend. It connects to the Django backend via HTTPS REST APIs.

---

## Configuring Mobile Server Address

Before building and running the mobile app on physical devices or emulators, set the backend API endpoint URL using the `NEXA_MOBILE_API_URL` environment variable:

### Production / Deployed Backend
```powershell
$env:NEXA_MOBILE_API_URL = "https://nexa-app-3f0z.onrender.com/api"
npm run sync:mobile
```

### Local Development / Cloudflare Tunnel
For local development, start the backend server with Cloudflare sharing:
```powershell
.\dev.ps1 -Share
```
Copy the printed `https://<random>.trycloudflare.com` public URL, append `/api`, set it in `$env:NEXA_MOBILE_API_URL`, and re-sync:
```powershell
$env:NEXA_MOBILE_API_URL = "https://<random>.trycloudflare.com/api"
npm run sync:mobile
```

---

## Building and Running on Android

### 1. Synchronize Web Assets
```powershell
$env:NEXA_MOBILE_API_URL = "https://nexa-app-3f0z.onrender.com/api"
npm run sync:mobile
```

### 2. Build Debug APK
```powershell
cd android
.\gradlew.bat assembleDebug
```

### 3. Install & Launch on Connected ADB Device
```powershell
adb install -r android/app/build/outputs/apk/debug/app-debug.apk
adb shell am start -S -n com.keynes.nexa/.MainActivity
```

Android uses the application ID `com.keynes.nexa`. This is a separate app from builds using the
previous `com.nexa.app` ID, so Android will not carry over their local app data automatically.
Confirm the ID is available in Play Console before publishing.
