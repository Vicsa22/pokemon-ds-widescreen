#pragma once
// Discord Rich Presence: "Playing Pokémon DS Widescreen — Pokémon SoulSilver, 1:23 elapsed" on
// the player's Discord profile, through Discord's local IPC connection (a named pipe on Windows,
// a socket on Linux and a Mac), without Discord's SDK: frontend/discord_rpc.cpp. PCs only; on the
// Switch and phones the functions do nothing. DISCORD PRESENCE in the settings turns it off.
#include <string>

namespace DiscordRpc
{
// The Discord application whose name and art the presence shows. Made once, free, at
// discord.com/developers/applications: New Application, named "Pokémon DS Widescreen"; its
// Application ID (General Information) goes here. Rich Presence > Art Assets there takes the
// games' pictures, named by their code in lower case (ipge, irbo, ...: `imageKey` below), which
// then show beside the text; a game without one shows the picture named "logo" there, and
// without that one, none (a presence never shows the application's own icon, nor anything but
// its art assets). Empty: no presence at all.
constexpr const char* ClientId = "1565789823959302224";

// Starts showing `details` (the game's name) with the time elapsed since now; `imageKey` names
// the art for it (see ClientId), `imageText` its caption. Connects when Discord is running, and
// Tick keeps trying when it is not.
void Start(const std::string& details, const std::string& imageKey, const std::string& imageText);
// Keeps the connection up: called once a frame (cheap; connects or reconnects every 15 seconds
// when Discord was not there or went away).
void Tick();
// Takes the presence down (Discord clears it when the connection closes).
void Stop();
// Whether a presence is up right now, confirmed by Discord (for the settings' line).
bool Connected();
// Whether Discord answered with an error or closed the connection (the reason is in the log):
// no more tries until Start is called again.
bool Refused();
}
