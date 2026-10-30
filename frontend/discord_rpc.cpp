// See discord_rpc.h. Discord's IPC: frames of a 4-byte opcode and a 4-byte length (little
// endian) followed by JSON. A HANDSHAKE (opcode 0) with the application's id opens the
// connection and Discord answers READY; then a FRAME (opcode 1) with the SET_ACTIVITY command
// shows the presence and Discord answers with the activity as set, or with an ERROR event. A
// CLOSE (opcode 2) from Discord carries the reason (4000: the application id is not known).
// Every answer is read: an error goes to the log (game.log), since otherwise a presence that
// Discord refused would look like one that is up. Closing the connection clears the presence.
// The connection is found at discord-ipc-0 .. discord-ipc-9: a named pipe on Windows, a socket
// in the runtime or temporary folder on Linux and a Mac (also where Flatpak's and Snap's Discord
// put it).
#include "discord_rpc.h"
#include "ssr_os.h"
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <ctime>
#include <string>
#include <vector>

#if defined(__SWITCH__) || defined(SSR_PHONE)
namespace DiscordRpc
{
void Start(const std::string&, const std::string&, const std::string&) {}
void Tick() {}
void Stop() {}
bool Connected() { return false; }
bool Refused() { return false; }
}
#else

#ifdef _WIN32
#include <windows.h>
#else
#include <poll.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>
#include <errno.h>
#include <cstdlib>
#endif

namespace DiscordRpc
{
namespace
{
#ifdef _WIN32
HANDLE Pipe = INVALID_HANDLE_VALUE;
bool IsOpen() { return Pipe != INVALID_HANDLE_VALUE; }
#else
int Sock = -1;
bool IsOpen() { return Sock >= 0; }
#endif
std::string Details, ImageText;
std::vector<std::string> Pictures; // names to try for the picture, the first one being asked for
long long StartedAt = 0;      // Unix seconds, the presence's "elapsed" clock
bool Wanted = false;          // Start called and not Stop
bool Ready = false;           // Discord answered the handshake
bool Up = false;              // Discord confirmed the activity
bool RefusedNow = false;      // Discord answered with an error or closed: no more tries
std::chrono::steady_clock::time_point LastTry;
bool TriedOnce = false;
unsigned Nonce = 0;
bool Announced = false;       // the log line about the connection, once

std::string Escaped(const std::string& s)
{
    std::string out;
    for (char c : s)
    {
        if (c == '"' || c == '\\') out += '\\';
        if ((unsigned char)c < 0x20) continue;
        out += c;
    }
    return out;
}

void Close()
{
#ifdef _WIN32
    if (Pipe != INVALID_HANDLE_VALUE) CloseHandle(Pipe);
    Pipe = INVALID_HANDLE_VALUE;
#else
    if (Sock >= 0) close(Sock);
    Sock = -1;
#endif
    Ready = Up = false;
}

bool WriteAll(const void* data, size_t len)
{
#ifdef _WIN32
    DWORD done = 0;
    while (len > 0)
    {
        if (!WriteFile(Pipe, data, (DWORD)len, &done, nullptr) || done == 0) return false;
        data = (const char*)data + done;
        len -= done;
    }
    return true;
#else
    while (len > 0)
    {
#ifdef MSG_NOSIGNAL
        const ssize_t n = send(Sock, data, len, MSG_NOSIGNAL);
#else
        const ssize_t n = send(Sock, data, len, 0);
#endif
        if (n <= 0) return false;
        data = (const char*)data + n;
        len -= (size_t)n;
    }
    return true;
#endif
}

bool SendFrame(unsigned opcode, const std::string& json)
{
    std::vector<char> frame(8 + json.size());
    const unsigned len = (unsigned)json.size();
    for (int i = 0; i < 4; i++)
    {
        frame[i] = (char)((opcode >> (8 * i)) & 0xFF);
        frame[4 + i] = (char)((len >> (8 * i)) & 0xFF);
    }
    memcpy(frame.data() + 8, json.data(), json.size());
    return WriteAll(frame.data(), frame.size());
}

// Whether Discord has sent something, waiting up to `ms` for it.
bool Pending(int ms)
{
#ifdef _WIN32
    for (;;)
    {
        DWORD avail = 0;
        if (!PeekNamedPipe(Pipe, nullptr, 0, nullptr, &avail, nullptr)) return false;
        if (avail > 0) return true;
        if (ms <= 0) return false;
        Sleep(10);
        ms -= 10;
    }
#else
    pollfd p = { Sock, POLLIN, 0 };
    return poll(&p, 1, ms) > 0;
#endif
}

// Reads exactly `len` bytes (Discord writes whole frames, so this does not wait long).
bool ReadAll(void* data, size_t len)
{
#ifdef _WIN32
    while (len > 0)
    {
        DWORD got = 0;
        if (!ReadFile(Pipe, data, (DWORD)len, &got, nullptr) || got == 0) return false;
        data = (char*)data + got;
        len -= got;
    }
    return true;
#else
    while (len > 0)
    {
        const ssize_t n = recv(Sock, data, len, 0);
        if (n <= 0) return false;
        data = (char*)data + n;
        len -= (size_t)n;
    }
    return true;
#endif
}

// Reads one frame, waiting up to `ms` for it to start. False: nothing came, or the connection
// went away (then it is closed).
bool ReadFrame(int ms, unsigned& opcode, std::string& json)
{
    if (!Pending(ms)) return false;
    unsigned char head[8];
    if (!ReadAll(head, 8))
    {
        Close();
        return false;
    }
    opcode = head[0] | head[1] << 8 | head[2] << 16 | (unsigned)head[3] << 24;
    const unsigned len = head[4] | head[5] << 8 | head[6] << 16 | (unsigned)head[7] << 24;
    if (len > 1 << 20)
    {
        Close();
        return false;
    }
    json.resize(len);
    if (len && !ReadAll(&json[0], len))
    {
        Close();
        return false;
    }
    return true;
}

bool Open()
{
    for (int i = 0; i < 10; i++)
    {
#ifdef _WIN32
        wchar_t name[64];
        swprintf(name, 64, L"\\\\.\\pipe\\discord-ipc-%d", i);
        Pipe = CreateFileW(name, GENERIC_READ | GENERIC_WRITE, 0, nullptr, OPEN_EXISTING, 0, nullptr);
        if (Pipe != INVALID_HANDLE_VALUE) return true;
#else
        const char* bases[] = { getenv("XDG_RUNTIME_DIR"), getenv("TMPDIR"), getenv("TMP"), getenv("TEMP"), "/tmp" };
        const char* subs[] = { "", "/app/com.discordapp.Discord", "/snap.discord" };
        for (const char* base : bases)
        {
            if (!base || !*base) continue;
            for (const char* sub : subs)
            {
                sockaddr_un addr = {};
                addr.sun_family = AF_UNIX;
                snprintf(addr.sun_path, sizeof addr.sun_path, "%s%s/discord-ipc-%d", base, sub, i);
                Sock = socket(AF_UNIX, SOCK_STREAM, 0);
                if (Sock < 0) return false;
#ifdef SO_NOSIGPIPE
                const int one = 1;
                setsockopt(Sock, SOL_SOCKET, SO_NOSIGPIPE, &one, sizeof one);
#endif
                if (connect(Sock, (sockaddr*)&addr, sizeof addr) == 0) return true;
                close(Sock);
                Sock = -1;
            }
        }
#endif
    }
    return false;
}

bool SetActivity()
{
#ifdef _WIN32
    const unsigned long pid = (unsigned long)GetCurrentProcessId();
#else
    const unsigned long pid = (unsigned long)getpid();
#endif
    std::string json = "{\"cmd\":\"SET_ACTIVITY\",\"args\":{\"pid\":" + std::to_string(pid) +
        ",\"activity\":{\"details\":\"" + Escaped(Details) + "\",\"timestamps\":{\"start\":" + std::to_string(StartedAt) + "}";
    if (!Pictures.empty())
        json += ",\"assets\":{\"large_image\":\"" + Escaped(Pictures.front()) + "\",\"large_text\":\"" + Escaped(ImageText) + "\"}";
    json += "}},\"nonce\":\"" + std::to_string(++Nonce) + "\"}";
    return SendFrame(1, json);
}

// Whether the answer has `"key": "value"` at its top level or anywhere (spaces around the colon
// or not: Discord's answers are not written by one program).
bool Has(const std::string& json, const char* key, const char* value)
{
    const std::string k = std::string("\"") + key + "\"";
    for (size_t at = json.find(k); at != std::string::npos; at = json.find(k, at + 1))
    {
        size_t p = at + k.size();
        while (p < json.size() && (json[p] == ' ' || json[p] == ':')) p++;
        if (json.compare(p, strlen(value) + 2, std::string("\"") + value + "\"") == 0) return true;
    }
    return false;
}

// What Discord answered. An error stops the tries: it is this program's or the application's
// fault, not Discord's absence, and the log says which.
void Handle(unsigned opcode, const std::string& json)
{
    if (opcode == 2)
    {
        fprintf(stderr, "[discord] connection closed by Discord: %s\n", json.c_str());
        Close();
        RefusedNow = true;
        return;
    }
    if (opcode != 1) return;
    if (Has(json, "evt", "ERROR"))
    {
        fprintf(stderr, "[discord] error: %s\n", json.c_str());
        Close();
        RefusedNow = true;
        return;
    }
    if (!Ready)
    {
        if (!Has(json, "evt", "READY")) return;
        Ready = true;
        if (!SetActivity()) Close();
        return;
    }
    if (Has(json, "cmd", "SET_ACTIVITY"))
    {
        Up = true;
        // (The activity as Discord stored it: what it dropped, such as a picture it does not
        // have, shows here.)
        if (!Announced) fprintf(stderr, "[discord] presence up: %s\n[discord] Discord's answer: %s\n", Details.c_str(), json.c_str());
        Announced = true;
        // A picture Discord does not have (no art asset of that name uploaded to the
        // application) is dropped from the answer, and the card shows a blank "?" in its place
        // (the application's own icon is not used for a presence): the next name is tried,
        // and with none left the activity goes without a picture.
        if (!Pictures.empty() && json.find("\"large_image\"") == std::string::npos)
        {
            fprintf(stderr, "[discord] no picture named %s in the application\n", Pictures.front().c_str());
            Pictures.erase(Pictures.begin());
            if (!SetActivity()) Close();
        }
    }
}

bool Connect()
{
    if (!Open()) return false;
    const std::string handshake = std::string("{\"v\":1,\"client_id\":\"") + ClientId + "\"}";
    if (!SendFrame(0, handshake))
    {
        Close();
        return false;
    }
    // Discord answers the handshake within a few milliseconds; the activity is sent on READY.
    unsigned opcode;
    std::string json;
    while (IsOpen() && !Ready && !RefusedNow && ReadFrame(1000, opcode, json)) Handle(opcode, json);
    if (IsOpen() && !Ready)
    {
        fprintf(stderr, "[discord] no answer to the handshake\n");
        Close();
    }
    return IsOpen();
}
}

void Start(const std::string& details, const std::string& imageKey, const std::string& imageText)
{
    Details = details;
    Pictures.clear();
    if (!imageKey.empty()) Pictures.push_back(imageKey);
    Pictures.push_back("logo");
    ImageText = imageText;
    if (!StartedAt) StartedAt = (long long)time(nullptr);
    Wanted = ClientId[0] != 0;
    if (!Wanted)
    {
        fprintf(stderr, "[discord] no application id built in (frontend/discord_rpc.h): no presence\n");
        return;
    }
    if (IsOpen() && Ready && !SetActivity()) Close(); // (a new game's name on a connection already up)
    TriedOnce = false;
    RefusedNow = false;
}

void Tick()
{
    if (!Wanted) return;
    const auto now = std::chrono::steady_clock::now();
    if (IsOpen())
    {
        unsigned opcode;
        std::string json;
        while (IsOpen() && ReadFrame(0, opcode, json)) Handle(opcode, json);
        return;
    }
    if (RefusedNow) return;
    if (TriedOnce && now - LastTry < std::chrono::seconds(15)) return;
    TriedOnce = true;
    LastTry = now;
    Connect();
}

void Stop()
{
    Wanted = false;
    if (IsOpen()) SendFrame(2, "{}");
    Close();
}

bool Connected() { return IsOpen() && Up; }
bool Refused() { return RefusedNow; }
}
#endif
