#pragma once
// Which kind of device this is built for, beyond what the compiler says:
//   SSR_IOS    an iPhone or iPad (the sideloaded app, tools/ios/build_all.sh)
//   SSR_PHONE  a phone or tablet, Android or iOS: touch controls on the screen, always full
//              screen, no keyboard shortcuts or desktop-only options. What only Android has (its
//              folder picker and Java calls, the check for a newer release) stays __ANDROID__.
#if defined(__APPLE__)
#include <TargetConditionals.h>
#if TARGET_OS_IPHONE
#define SSR_IOS 1
#endif
#endif
#if defined(__ANDROID__) || defined(SSR_IOS)
#define SSR_PHONE 1
#endif
