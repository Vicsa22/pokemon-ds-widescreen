# Descargas de prueba: el programa de PC con las copias españolas

Construidas con `tools/pc/build_all.sh both -` (sin la ROM de SoulSilver), desde este
repositorio; no contienen nada de los juegos, sólo el programa y sus tablas de direcciones.

| Archivo | Para |
|---|---|
| `pokemon-ds-wide-pc-windows-x86_64.zip` | Windows: `Pokemon DS Launcher.exe` |
| `pokemon-ds-wide-pc-linux-x86_64.tar.gz` | Linux y Steam Deck: `pokemon-ds-wide` |

Descomprime, copia tus ROMs a la carpeta `roms` (con cualquier nombre) y abre el programa.
Juegan: Negro, Blanco, Negro 2 y Blanco 2 en inglés; Platinum US; y las copias españolas de
Blanco (`IRAS`), Blanco 2 (`IRDS`) y Platino (`CPUS`). SoulSilver y HeartGold no van en esta
construcción (sus tablas necesitan la ROM de SoulSilver US al compilar): la lista los muestra
como juegos que esta descarga no tiene. Negro y Negro 2 en español tampoco, a falta de sus ROMs.

Las copias españolas aparecen con su nombre (POKEMON BLANCO 2...), guardan la partida con el
sufijo `-es` (`saves/white2-es.sav`) y muestran la carátula de la copia inglesa.

Probado sin ventana en Linux (Blanco 2, Blanco y Platino en español, sesiones largas sin fallos);
no probado con pantalla ni con mando en Windows. Si algo se ve mal, adjunta `game.log`.
