"""Serve the offline editor on loopback and broker explicit ChatGPT/Codex jobs."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
import secrets
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Lock
import urllib.error
import urllib.request
import webbrowser
from zipfile import ZipFile, BadZipFile

from building_damage_codex import MAX_ZIP_BYTES, execute, load_request
from sprite_codex_session import session

HOST = "127.0.0.1"
PORT = 43789
EDITOR = Path(__file__).resolve().parents[1] / "extras" / "sprite-editor"


class EditorServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port=PORT):
        super().__init__((HOST, port), EditorHandler)
        self.host = f"{HOST}:{self.server_port}"
        self.origin = f"http://{self.host}"
        self.token = secrets.token_urlsafe(32)
        self.codex_lock = Lock()


class EditorHandler(BaseHTTPRequestHandler):
    server: EditorServer

    def setup(self):
        super().setup()
        self.connection.settimeout(20)

    def log_message(self, *_):
        pass

    def respond(self, code, body, mime):
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-SpriteSuite-Editor", "1")
        self.end_headers()
        self.wfile.write(body)

    def json(self, code, value):
        self.respond(code, json.dumps(value, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self):
        filenames = {"/": "Stronghold_Sprite_Editor.html",
                     "/en": "Stronghold_Sprite_Editor_EN.html"}
        if self.headers.get("Host") != self.server.host or self.path not in filenames:
            return self.json(404, {"error": "Unbekannter Editor-Pfad."})
        html = (EDITOR / filenames[self.path]).read_text(encoding="utf-8")
        html = html.replace("connect-src 'none'", "connect-src 'self'", 1)
        html = html.replace("<head>", '<head>\n<meta name="spritesuite-local" content="'
                            + self.server.token + '">', 1)
        self.respond(200, html.encode("utf-8"), "text/html; charset=utf-8")

    def do_POST(self):
        token = self.headers.get("X-SpriteSuite-Session", "")
        if (self.headers.get("Host") != self.server.host
                or self.headers.get("Origin") != self.server.origin
                or not secrets.compare_digest(token.encode("utf-8"), self.server.token.encode("ascii"))):
            return self.json(403, {"error": "Ungültige lokale Editor-Sitzung."})
        if self.path not in {"/codex/status", "/codex/login", "/codex/generate"}:
            return self.json(404, {"error": "Unbekannte Codex-Aktion."})
        if not self.server.codex_lock.acquire(blocking=False):
            return self.json(409, {"error": "In diesem Editor läuft bereits ein Codex-Auftrag."})
        try:
            size = int(self.headers.get("Content-Length", 0))
            if self.path == "/codex/generate":
                if self.headers.get_content_type() != "application/zip" or not 0 < size <= MAX_ZIP_BYTES:
                    return self.json(413, {"error": "Ungültiges oder zu großes Anfrage-ZIP."})
                body = self.rfile.read(size)
                if len(body) != size:
                    return self.json(400, {"error": "Unvollständiges Anfrage-ZIP."})
                request, images = load_request(BytesIO(body))
                with TemporaryDirectory(prefix="spritesuite-candidate-") as folder:
                    output = Path(folder) / "result"
                    execute(request, images, output)
                    response = BytesIO()
                    with ZipFile(response, "w") as archive:
                        for entry in output.iterdir():
                            archive.write(entry, entry.name)
                self.respond(200, response.getvalue(), "application/zip")
            else:
                if size:
                    return self.json(400, {"error": "Diese Aktion erwartet keine Dateien."})
                with TemporaryDirectory(prefix="spritesuite-codex-") as folder, session(Path(folder)) as codex:
                    if self.path == "/codex/login":
                        codex.login()
                    self.json(200, {"chatgptConnected": codex.connected()})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except (ValueError, KeyError, OSError, BadZipFile) as exc:
            try:
                self.json(422, {"error": str(exc)})
            except (BrokenPipeError, ConnectionResetError):
                pass
        finally:
            self.server.codex_lock.release()


def open_editor(language):
    """Launch the local editor; fall back to the self-contained editor on port conflict."""
    route = "/en" if language == "en" else "/"
    try:
        server = EditorServer()
    except OSError:
        url = f"http://{HOST}:{PORT}{route}"
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.headers.get("X-SpriteSuite-Editor") == "1":
                    webbrowser.open(url)
                    return
        except (OSError, urllib.error.URLError):
            pass
        filename = "Stronghold_Sprite_Editor_EN.html" if language == "en" else "Stronghold_Sprite_Editor.html"
        webbrowser.open((EDITOR / filename).as_uri())
        return
    with server:
        from threading import Timer
        opener = Timer(0.1, webbrowser.open, args=(server.origin + route,))
        opener.daemon = True
        opener.start()
        server.serve_forever()


def launch(language):
    subprocess.Popen([sys.executable, str(Path(__file__).resolve()), language],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


if __name__ == "__main__":
    open_editor("en" if sys.argv[1:] == ["en"] else "de")