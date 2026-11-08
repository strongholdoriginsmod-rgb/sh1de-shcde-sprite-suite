"""Serve the offline editor on loopback and broker explicit ChatGPT/Codex jobs."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
import secrets
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Lock
import urllib.error
import urllib.request
import webbrowser
from zipfile import ZipFile, BadZipFile

from building_damage_codex import execute as execute_damage, load_request as load_damage_request
from suite_ai_codex import MAX_BUNDLE, execute as execute_workshop, load_request as load_workshop_request
from sprite_codex_session import session
from sprite_editor_native_broker import BrokerError, NativeBroker, write_registry

HOST = "127.0.0.1"
PORT = 43789
EDITOR = Path(__file__).resolve().parents[1] / "extras" / "sprite-editor"


def image_job(body: bytes) -> tuple[dict, object, object]:
    """Dispatch both validated request formats without weakening either contract."""
    if not 0 < len(body) <= MAX_BUNDLE:
        raise ValueError("Bildauftrag überschreitet das ZIP-Dateibudget.")
    with ZipFile(BytesIO(body)) as archive:
        entries = archive.infolist()
        requests = [entry for entry in entries if entry.filename == "request.json"]
        if len(requests) != 1 or requests[0].file_size > 128 * 1024:
            raise ValueError("Unzulässige Anfrage-Metadaten im Bildauftrag.")
        request = json.loads(archive.read(requests[0]))
    if not isinstance(request, dict):
        raise ValueError("Bildauftrag benötigt ein JSON-Objekt.")
    if request.get("format") == "sprite-suite.ai-image-edit":
        checked, images = load_workshop_request(BytesIO(body))
        return checked, images, execute_workshop
    checked, images = load_damage_request(BytesIO(body))
    return checked, images, execute_damage


class EditorServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = sys.platform != "win32"

    def server_bind(self):
        # A capability registry must identify one server, never two Windows
        # listeners sharing SO_REUSEADDR on the same loopback endpoint.
        if sys.platform == "win32":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def __init__(self, port=PORT, *, registry_path=None):
        super().__init__((HOST, port), EditorHandler)
        self.host = f"{HOST}:{self.server_port}"
        self.origin = f"http://{self.host}"
        self.token = secrets.token_urlsafe(32)
        self.codex_lock = Lock()
        self.desktop_nonce = secrets.token_urlsafe(32)
        self.native = NativeBroker()
        self.registry_path = Path(registry_path) if registry_path is not None else None
        if self.registry_path:
            try:
                write_registry(self.registry_path, origin=self.origin, nonce=self.desktop_nonce)
            except OSError:
                self.server_close()
                raise

    def server_close(self):
        native = getattr(self, "native", None)
        if native is not None:
            native.close()
        registry_path = getattr(self, "registry_path", None)
        if registry_path:
            try:
                current = json.loads(registry_path.read_text("utf-8"))
                if secrets.compare_digest(current.get("sessionNonce", ""), self.desktop_nonce):
                    registry_path.unlink()
            except (OSError, ValueError):
                pass
        super().server_close()


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
        if self.path.startswith("/native/"):
            return self.native_post()
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
                if self.headers.get_content_type() != "application/zip" or not 0 < size <= MAX_BUNDLE:
                    return self.json(413, {"error": "Ungültiges oder zu großes Anfrage-ZIP."})
                body = self.rfile.read(size)
                if len(body) != size:
                    return self.json(400, {"error": "Unvollständiges Anfrage-ZIP."})
                request, images, execute = image_job(body)
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

    def native_post(self):
        origin = self.headers.get("Origin")
        browser = (origin == self.server.origin and secrets.compare_digest(
            self.headers.get("X-SpriteSuite-Session", "").encode("utf-8"), self.server.token.encode("ascii")))
        desktop = (origin in {None, self.server.origin} and secrets.compare_digest(
            self.headers.get("X-SpriteSuite-Desktop-Session", "").encode("utf-8"), self.server.desktop_nonce.encode("ascii")))
        if self.headers.get("Host") != self.server.host or not (browser or desktop):
            return self.json(403, {"ok": False, "error": {"code": "forbidden", "message": "Invalid local editor session."}})
        routes = {"/native/state": (desktop, self.server.native.state),
                  "/native/execute": (desktop, self.server.native.execute),
                  "/native/cancel": (desktop, self.server.native.cancel),
                  "/native/poll": (browser, self.server.native.poll),
                  "/native/result": (browser, self.server.native.result)}
        if self.path not in routes or not routes[self.path][0]:
            return self.json(403, {"ok": False, "error": {"code": "forbidden", "message": "Invalid native client role."}})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if self.headers.get_content_type() != "application/json" or not 0 < size <= 192 * 1024 * 1024:
                raise BrokerError("invalid", "Invalid native JSON request size.", 413)
            raw = self.rfile.read(size)
            if len(raw) != size:
                raise BrokerError("invalid", "Incomplete native request.", 400)
            body = json.loads(raw)
            if not isinstance(body, dict):
                raise BrokerError("invalid", "Expected a native request object.", 400)
            result = routes[self.path][1](body)
            timeout = result.get("error", {}).get("code") == "timeout"
            self.json(408 if timeout else 200, result)
        except BrokerError as exc:
            self.json(exc.status, {"ok": False, "error": {"code": exc.code, "message": str(exc)}})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except (ValueError, OSError) as exc:
            self.json(400, {"ok": False, "error": {"code": "invalid", "message": str(exc)}})


def open_editor(language, area=None):
    """Launch the local editor; fall back to the self-contained editor on port conflict."""
    if area not in {None, "geometry", "ai", "damage"}:
        raise ValueError("Unbekannter Editorbereich.")
    route = ("/en" if language == "en" else "/")
    fragment = "#" + area if area else ""
    try:
        server = EditorServer(registry_path=Path(__file__).resolve().parents[1] / "work/session-registry.json")
    except OSError:
        url = f"http://{HOST}:{PORT}{route}"
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.headers.get("X-SpriteSuite-Editor") == "1":
                    webbrowser.open(url + fragment)
                    return
        except (OSError, urllib.error.URLError):
            pass
        filename = "Stronghold_Sprite_Editor_EN.html" if language == "en" else "Stronghold_Sprite_Editor.html"
        webbrowser.open((EDITOR / filename).as_uri() + fragment)
        return
    with server:
        from threading import Timer
        opener = Timer(0.1, webbrowser.open, args=(server.origin + route + fragment,))
        opener.daemon = True
        opener.start()
        server.serve_forever()


def launch(language, area=None):
    if area not in {None, "geometry", "ai", "damage"}:
        raise ValueError("Unbekannter Editorbereich.")
    command = [sys.executable, str(Path(__file__).resolve()), language]
    if area:
        command.extend(["--area", area])
    subprocess.Popen(command,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("language", choices=("de", "en"), nargs="?", default="de")
    parser.add_argument("--area", choices=("geometry", "ai", "damage"))
    args = parser.parse_args()
    open_editor(args.language, args.area)
