// Windows: diagnostics for game.log. A crash is written there with the exception's code, the
// faulting address and the module it is in, so that a report says where it happened (the
// window closes with nothing said otherwise); and the overlays that hook the graphics APIs
// (RivaTuner Statistics Server, which MSI Afterburner uses, Steam's, Discord's, GeForce
// Experience's) are named when their DLL is in this process, since one of them crashed the
// game when it started (issue #7). Only this file sees windows.h: its macros clash with
// melonDS's names in main.cpp.
#ifdef _WIN32
#include "win_diag.h"
#include <windows.h>
#include <cstdio>

namespace
{
LONG WINAPI OnCrash(EXCEPTION_POINTERS* ep)
{
    const EXCEPTION_RECORD* r = ep && ep->ExceptionRecord ? ep->ExceptionRecord : nullptr;
    const void* at = r ? r->ExceptionAddress : nullptr;
    char module[MAX_PATH] = "?";
    HMODULE mod = nullptr;
    size_t offset = 0;
    if (at && GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
            (LPCSTR)at, &mod) && mod)
    {
        GetModuleFileNameA(mod, module, sizeof module);
        offset = (size_t)((const char*)at - (const char*)mod);
    }
    fprintf(stderr, "[crash] exception 0x%08lx at %p: %s+0x%zx (thread %lu)\n",
        r ? (unsigned long)r->ExceptionCode : 0ul, at, module, offset, (unsigned long)GetCurrentThreadId());
    if (r && r->ExceptionCode == EXCEPTION_ACCESS_VIOLATION && r->NumberParameters >= 2)
        fprintf(stderr, "[crash] %s address %p\n", r->ExceptionInformation[0] == 0 ? "reading" : r->ExceptionInformation[0] == 1 ? "writing" : "running",
            (void*)r->ExceptionInformation[1]);
    fflush(stderr);
    return EXCEPTION_CONTINUE_SEARCH; // (Windows then ends the program as it would have)
}
}

void SsrWinDiagStart()
{
    SetUnhandledExceptionFilter(OnCrash);
    // Overlays that hook Direct3D and OpenGL in every process that draws with them.
    static const struct { const char* dll; const char* name; } overlays[] = {
        { "RTSSHooks64.dll", "RivaTuner Statistics Server (MSI Afterburner's overlay)" },
        { "RTSSHooks.dll", "RivaTuner Statistics Server (MSI Afterburner's overlay)" },
        { "GameOverlayRenderer64.dll", "Steam's overlay" },
        { "DiscordHook64.dll", "Discord's overlay" },
        { "nvspcap64.dll", "GeForce Experience's overlay" },
    };
    for (const auto& o : overlays)
        if (GetModuleHandleA(o.dll))
            fprintf(stderr, "[windows] %s is in this process (%s)\n", o.name, o.dll);
}
#endif
