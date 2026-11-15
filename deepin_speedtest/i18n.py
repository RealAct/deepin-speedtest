"""Translations. English is the source language; Spanish is built in.

The language follows the system: Spanish when the session's locale is
Spanish (``LANGUAGE``, ``LC_ALL``, ``LC_MESSAGES`` or ``LANG`` starts with
``es``), English otherwise. The texts live in this file as plain data, so no
translation files are read or parsed at run time.

``tr(text)`` returns the translation of an English text, or the text itself
when there is none. Messages that come from the engine are passed through
``tr`` in the UI, which only ever replaces a known, fixed message by its
fixed translation.
"""

from __future__ import annotations

import os
from typing import Dict, Mapping, Optional

LANGUAGES = ("en", "es")


def detect_language(environ: Optional[Mapping[str, str]] = None) -> str:
    """Return "es" for a Spanish session, else "en" (POSIX precedence)."""
    env = os.environ if environ is None else environ
    locale = env.get("LC_ALL") or env.get("LC_MESSAGES") or env.get("LANG") or ""
    if locale.split(".")[0] in ("C", "POSIX"):
        return "en"  # as gettext does, LANGUAGE is ignored in the C locale
    for value in (env.get("LANGUAGE", "").split(":")[0], locale):
        if value:
            return "es" if value.lower().split(".")[0].split("_")[0].split("-")[0] == "es" else "en"
    return "en"


_language = detect_language()


def language() -> str:
    return _language


def set_language(code: str) -> None:
    global _language
    _language = code if code in LANGUAGES else "en"


def tr(text: str) -> str:
    if _language == "es":
        return ES.get(text, text)
    return text


ES: Dict[str, str] = {
    # -- main window ---------------------------------------------------
    "Speed test": "Prueba de velocidad",
    "History": "Historial",
    "Options": "Opciones",
    "About": "Acerca de",
    "Test server": "Servidor de prueba",
    "Find servers": "Buscar servidores",
    "Look up nearby public servers": "Buscar servidores públicos cercanos",
    "Add…": "Añadir…",
    "Add your own self-hosted ndt7 or LibreSpeed server":
        "Añadir tu propio servidor ndt7 o LibreSpeed",
    "Remove": "Quitar",
    "Start test": "Iniciar prueba",
    "Stop": "Detener",
    "Ping": "Ping",
    "Jitter": "Jitter",
    "Download": "Descarga",
    "Upload": "Subida",
    "Choose a server and press Start.": "Elige un servidor y pulsa Iniciar.",
    "Ready": "Listo",
    "Speed gauge": "Indicador de velocidad",
    "Measuring latency": "Midiendo la latencia",
    "Error": "Error",
    "Done": "Terminado",
    "Nearest public server (%s, automatic)": "Servidor público más cercano (%s, automático)",
    "%s · %s (self-hosted %s)": "%s · %s (%s propio)",
    "Self-hosted": "Propio",
    "Could not save settings: %s": "No se pudo guardar la configuración: %s",
    "Looking up nearby %s servers…": "Buscando servidores %s cercanos…",
    "Found %d nearby servers.": "Se encontraron %d servidores cercanos.",
    "Test cancelled.": "Prueba cancelada.",
    "Finding the best server…": "Buscando el mejor servidor…",
    "Testing with %s (%s)…": "Probando con %s (%s)…",
    "loaded latency %s ms": "latencia con carga %s ms",
    "Tested with %s (%s) · %s": "Probado con %s (%s) · %s",
    " (not saved: %s)": " (no guardado: %s)",
    "Stop the running test before changing options.":
        "Detén la prueba en curso antes de cambiar las opciones.",
    "Options saved.": "Opciones guardadas.",
    "Internal error: %s": "Error interno: %s",

    # -- history -------------------------------------------------------
    "Date": "Fecha",
    "Server": "Servidor",
    "Down": "Bajada",
    "Up": "Subida",
    "Idle latency, ms": "Latencia en reposo, ms",
    "Jitter, ms": "Jitter, ms",
    "Download, Mbit/s": "Descarga, Mbit/s",
    "Upload, Mbit/s": "Subida, Mbit/s",
    "Export CSV…": "Exportar CSV…",
    "Delete": "Eliminar",
    "Clear all": "Borrar todo",
    "%d tests · average %s↓ / %s↑ Mbit/s": "%d pruebas · media %s↓ / %s↑ Mbit/s",
    "No tests yet. Results are stored only on this computer.":
        "Aún no hay pruebas. Los resultados se guardan solo en este equipo.",
    "Export history": "Exportar historial",
    "CSV files (*.csv)": "Archivos CSV (*.csv)",
    "Could not export: %s": "No se pudo exportar: %s",
    "Delete all saved results?": "¿Eliminar todos los resultados guardados?",

    # -- standard buttons ----------------------------------------------
    "OK": "Aceptar",
    "Cancel": "Cancelar",
    "Close": "Cerrar",
    "Yes": "Sí",
    "No": "No",

    # -- consent -------------------------------------------------------
    "Public test servers": "Servidores de prueba públicos",
    "Use M-Lab servers": "Usar servidores de M-Lab",
    "<p><b>About the public M-Lab servers</b></p>"
    "<p>By default Deepin Speedtest measures against servers run by "
    "<a href='https://www.measurementlab.net/'>Measurement Lab (M-Lab)</a>, an open, "
    "non-profit research platform. Using them is free and needs no account.</p>"
    "<p><b>Privacy:</b> M-Lab publishes every test as open data for research, "
    "<b>including your public IP address</b>. See M-Lab's "
    "<a href='https://www.measurementlab.net/privacy/'>privacy policy</a>.</p>"
    "<p>Deepin Speedtest itself collects nothing: no telemetry, no accounts, no ads. "
    "If you prefer, choose <i>Cancel</i> and add your own self-hosted ndt7 or "
    "LibreSpeed server instead.</p>":
        "<p><b>Acerca de los servidores públicos de M-Lab</b></p>"
        "<p>De forma predeterminada, Deepin Speedtest mide contra servidores de "
        "<a href='https://www.measurementlab.net/'>Measurement Lab (M-Lab)</a>, una plataforma "
        "de investigación abierta y sin ánimo de lucro. Usarlos es gratis y no requiere cuenta.</p>"
        "<p><b>Privacidad:</b> M-Lab publica cada prueba como datos abiertos para la "
        "investigación, <b>incluida tu dirección IP pública</b>. Consulta la "
        "<a href='https://www.measurementlab.net/privacy/'>política de privacidad</a> de M-Lab.</p>"
        "<p>Deepin Speedtest no recopila nada: sin telemetría, sin cuentas y sin anuncios. "
        "Si lo prefieres, elige <i>Cancelar</i> y añade tu propio servidor ndt7 o "
        "LibreSpeed.</p>",

    # -- add server ----------------------------------------------------
    "Add a self-hosted server": "Añadir un servidor propio",
    "ndt7 server (m-lab/ndt-server)": "Servidor ndt7 (m-lab/ndt-server)",
    "LibreSpeed server": "Servidor LibreSpeed",
    "Home lab": "Mi servidor",
    "Type": "Tipo",
    "Name": "Nombre",
    "Address": "Dirección",
    "speed.example.org or speed.example.org:4443": "speed.example.org o speed.example.org:4443",
    "Host name (and optional port) of an ndt7 server with a valid TLS "
    "certificate. Plain ws:// is not supported.":
        "Nombre de host (y puerto opcional) de un servidor ndt7 con un certificado TLS "
        "válido. No se admite ws:// sin cifrar.",
    "Base https:// URL of a LibreSpeed install (the folder that contains "
    "backend/garbage.php). Plain http:// is not supported.":
        "URL https:// base de una instalación de LibreSpeed (la carpeta que contiene "
        "backend/garbage.php). No se admite http:// sin cifrar.",

    # -- options -------------------------------------------------------
    "M-Lab (Measurement Lab)": "M-Lab (Measurement Lab)",
    "LibreSpeed public servers": "Servidores públicos de LibreSpeed",
    "Open research platform using the ndt7 protocol, one connection per direction. "
    "M-Lab publishes every test, including your IP address, as open data.":
        "Plataforma de investigación abierta que usa el protocolo ndt7, con una conexión por "
        "sentido. M-Lab publica cada prueba, incluida tu dirección IP, como datos abiertos.",
    "Volunteer-run open-source servers, several parallel connections. Results are not "
    "published, but the server operator sees your IP address. Best choice for "
    "multi-gigabit lines.":
        "Servidores de código abierto gestionados por voluntarios, con varias conexiones en "
        "paralelo. Los resultados no se publican, pero el operador del servidor ve tu "
        "dirección IP. La mejor opción para líneas de varios gigabits.",
    "Maximum speed": "Velocidad máxima",
    "Up to 1 Gbit/s": "Hasta 1 Gbit/s",
    "Up to 2.5 Gbit/s": "Hasta 2,5 Gbit/s",
    "Up to 5 Gbit/s": "Hasta 5 Gbit/s",
    "Sets the range of the dial. Above 1 Gbit/s, LibreSpeed tests also use more parallel "
    "connections and larger transfers. Results depend on the server's own capacity: "
    "few public servers can deliver 5 Gbit/s.":
        "Define el rango del indicador. Por encima de 1 Gbit/s, las pruebas con LibreSpeed "
        "usan además más conexiones en paralelo y transferencias mayores. Los resultados "
        "dependen de la capacidad del servidor: pocos servidores públicos pueden ofrecer "
        "5 Gbit/s.",
    "Speedtest.net servers are not offered: Ookla does not license them for "
    "third-party apps. Your own ndt7 or LibreSpeed server can be added with “Add…”.":
        "No se ofrecen los servidores de Speedtest.net: Ookla no concede licencias para "
        "aplicaciones de terceros. Puedes añadir tu propio servidor ndt7 o LibreSpeed con "
        "«Añadir…».",

    # -- about and credits ---------------------------------------------
    "About %s": "Acerca de %s",
    "Credits": "Créditos",
    "<h3>%s %s</h3>"
    "<p>Created by Eli Linares for %s</p>"
    "<p>An open-source internet speed test for Deepin and other Debian-based desktops.</p>"
    "<p>Measures latency, jitter, download and upload using the open ndt7 protocol "
    "(M-Lab or self-hosted) or LibreSpeed servers (public or self-hosted).</p>"
    "<p><b>Privacy:</b> no telemetry, no accounts. History is stored only on this computer.</p>"
    "<p><b>Engine sandbox:</b> %s</p>"
    "<p>A community project. Not affiliated with Deepin Technology, Ookla® or Speedtest®.</p>":
        "<h3>%s %s</h3>"
        "<p>Creado por Eli Linares para %s</p>"
        "<p>Una prueba de velocidad de internet de código abierto para Deepin y otros "
        "escritorios basados en Debian.</p>"
        "<p>Mide la latencia, el jitter, la descarga y la subida con el protocolo abierto ndt7 "
        "(M-Lab o servidor propio) o con servidores LibreSpeed (públicos o propios).</p>"
        "<p><b>Privacidad:</b> sin telemetría y sin cuentas. El historial se guarda solo en "
        "este equipo.</p>"
        "<p><b>Aislamiento del motor:</b> %s</p>"
        "<p>Un proyecto de la comunidad. No está afiliado a Deepin Technology, Ookla® ni "
        "Speedtest®.</p>",
    "<h3>Credits</h3>"
    "<p>Created by Eli Linares<br><br>%s</p>"
    "<p>Test servers: Measurement Lab (M-Lab) and the LibreSpeed project and its "
    "volunteer server operators.</p>":
        "<h3>Créditos</h3>"
        "<p>Creado por Eli Linares<br><br>%s</p>"
        "<p>Servidores de prueba: Measurement Lab (M-Lab) y el proyecto LibreSpeed y sus "
        "operadores de servidores voluntarios.</p>",
    "The link could not be opened. Copy it into your browser instead:\n\n%s":
        "No se pudo abrir el enlace. Cópialo en tu navegador:\n\n%s",
    "Run a test to see the engine sandbox status.":
        "Ejecuta una prueba para ver el estado del aislamiento del motor.",
    "Landlock ABI %d active (files, exec%s restricted)":
        "Landlock ABI %d activo (archivos, ejecución%s restringidos)",
    ", TCP ports": ", puertos TCP",
    "Landlock unavailable on this kernel; resource limits and no_new_privs active":
        "Landlock no está disponible en este núcleo; límites de recursos y no_new_privs activos",

    # -- engine and connection errors ----------------------------------
    "Engine sent an oversized message.": "El motor envió un mensaje demasiado grande.",
    "Engine protocol error: %s": "Error de protocolo del motor: %s",
    "The test took too long and was stopped.": "La prueba tardó demasiado y se detuvo.",
    "Could not start the measurement engine.": "No se pudo iniciar el motor de medición.",
    "The measurement engine stopped unexpectedly.":
        "El motor de medición se detuvo inesperadamente.",
    "The server's TLS certificate could not be verified.":
        "No se pudo verificar el certificado TLS del servidor.",
    "A secure (TLS) connection could not be established.":
        "No se pudo establecer una conexión segura (TLS).",
    "The server name could not be resolved. Check your connection.":
        "No se pudo resolver el nombre del servidor. Comprueba tu conexión.",
    "The server stopped responding.": "El servidor dejó de responder.",
    "no usable M-Lab servers were returned": "no se recibió ningún servidor de M-Lab utilizable",
    "no usable LibreSpeed servers were returned":
        "no se recibió ningún servidor de LibreSpeed utilizable",
    "Locate API returned invalid JSON": "la API Locate devolvió un JSON no válido",
    "Locate API returned an unexpected document":
        "la API Locate devolvió un documento inesperado",
    "LibreSpeed server list is not valid JSON":
        "la lista de servidores de LibreSpeed no es un JSON válido",
    "LibreSpeed server list has an unexpected format":
        "la lista de servidores de LibreSpeed tiene un formato inesperado",
    "no answer from engine": "el motor no respondió",
    "test failed": "la prueba falló",

    # -- address validation (Add server, --ndt7-server, --librespeed) ---
    "invalid host name": "nombre de host no válido",
    "invalid port": "puerto no válido",
    "invalid URL": "URL no válida",
    "invalid URL path": "ruta de URL no válida",
    "only https:// or wss:// servers are allowed": "solo se permiten servidores https:// o wss://",
    "only https:// URLs are allowed": "solo se permiten URL https://",
    "credentials in URLs are not allowed": "no se permiten credenciales en las URL",
    "enter just a host name (and optional port)":
        "escribe solo un nombre de host (y un puerto opcional)",
    "the server URL must not contain ? or #": "la URL del servidor no debe contener ? ni #",
    "expected a string": "se esperaba un texto",

    # -- terminal mode -------------------------------------------------
    "Deepin Speedtest uses the public servers of Measurement Lab (M-Lab) by default.\n"
    "M-Lab publishes every test as open research data, INCLUDING YOUR PUBLIC IP\n"
    "ADDRESS (https://www.measurementlab.net/privacy/). Deepin Speedtest itself collects\n"
    "nothing. Use --ndt7-server or --librespeed to test against your own server.\n":
        "Deepin Speedtest usa de forma predeterminada los servidores públicos de Measurement\n"
        "Lab (M-Lab). M-Lab publica cada prueba como datos abiertos de investigación,\n"
        "INCLUIDA TU DIRECCIÓN IP PÚBLICA (https://www.measurementlab.net/privacy/).\n"
        "Deepin Speedtest no recopila nada. Usa --ndt7-server o --librespeed para probar\n"
        "contra tu propio servidor.\n",
    "Re-run with --accept-mlab-privacy to continue.\n":
        "Vuelve a ejecutar con --accept-mlab-privacy para continuar.\n",
    "Continue with M-Lab servers? [y/N] ": "¿Continuar con los servidores de M-Lab? [s/N] ",
    "%s %s command-line speed test": "%s %s, prueba de velocidad en la terminal",
    "list nearby public servers": "mostrar los servidores públicos cercanos",
    "public server network (default: the one chosen in Options, else mlab)":
        "red de servidores públicos (por defecto: la elegida en Opciones; si no, mlab)",
    "tune for lines faster than 1 Gbit/s (more parallel streams with LibreSpeed)":
        "ajustar para líneas de más de 1 Gbit/s (más conexiones en paralelo con LibreSpeed)",
    "use a self-hosted ndt7 server": "usar un servidor ndt7 propio",
    "use a self-hosted LibreSpeed server (https://...)":
        "usar un servidor LibreSpeed propio (https://...)",
    "print the result as JSON": "mostrar el resultado en JSON",
    "do not add the result to the history": "no añadir el resultado al historial",
    "accept the M-Lab data notice": "aceptar el aviso de datos de M-Lab",
    "error: %s\n": "error: %s\n",
    "Server: %s (%s)\n": "Servidor: %s (%s)\n",
    "jitter": "jitter",
    "usage: deepin-speedtest [--cli [options] | --version]\n"
    "Run without arguments for the desktop app; 'deepin-speedtest --cli --help' for the terminal.":
        "uso: deepin-speedtest [--cli [opciones] | --version]\n"
        "Ejecútalo sin argumentos para la aplicación de escritorio; "
        "'deepin-speedtest --cli --help' para la terminal.",
}
