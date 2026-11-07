"""Local Codex client for SpriteSuite image jobs, using managed ChatGPT login."""
from __future__ import annotations

import base64
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
from queue import Empty, Queue
import shutil
import subprocess
from threading import Thread
import time
from urllib.parse import urlsplit
import webbrowser


class CodexError(ValueError):
    """A user-facing Codex workflow error."""


def codex_command() -> list[str]:
    native = shutil.which("codex.exe" if os.name == "nt" else "codex")
    if native:
        return [native]
    if os.name == "nt":
        # npm adds a batch shim to PATH. Use its JS entry point without cmd.exe.
        shim = shutil.which("codex.cmd")
        node = shutil.which("node.exe")
        if shim and node:
            script = Path(shim).parent / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
            if script.is_file():
                return [node, str(script)]
    raise CodexError("Codex CLI fehlt im PATH. Installiere oder aktualisiere den offiziellen Codex-Client.")


class CodexSession:
    def __init__(self, cwd: Path):
        env = {key: value for key, value in os.environ.items() if key.upper() not in {
            "OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN", "OPENAI_BASE_URL",
            "OPENAI_API_BASE", "AZURE_OPENAI_API_KEY", "CODEX_CHATGPT_BASE_URL"
        }}
        self.process = subprocess.Popen([
            *codex_command(), "app-server", "-c", 'forced_login_method="chatgpt"',
            "-c", 'model_provider="openai"', "-c", 'mcp_servers={}',
            "-c", 'web_search="disabled"', "--disable", "hooks", "--disable", "shell_tool",
            "--disable", "unified_exec", "--disable", "multi_agent", "--disable", "view_image",
            "--disable", "plugins", "--enable", "image_generation",
        ], cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.messages = Queue()
        self.request_id = 0
        self.pending = []
        self.home = Path(env.get("CODEX_HOME") or Path.home() / ".codex")
        Thread(target=self._read, daemon=True).start()

    def _read(self):
        try:
            for line in self.process.stdout:
                self.messages.put(json.loads(line))
        except (ValueError, OSError):
            pass
        finally:
            self.messages.put(None)

    def send(self, message):
        try:
            self.process.stdin.write(json.dumps(message) + "\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise CodexError("Codex hat die lokale Verbindung beendet.") from exc

    def receive(self, deadline):
        try:
            message = self.messages.get(timeout=max(0, deadline - time.monotonic()))
        except Empty as exc:
            raise CodexError("Codex antwortet nicht mehr oder der Vorgang hat zu lange gedauert.") from exc
        if message is None:
            raise CodexError("Codex hat die Verbindung beendet. Prüfe die Installation und die ChatGPT-Anmeldung.")
        return message

    def request(self, method, params, timeout=30):
        self.request_id += 1
        request_id = self.request_id
        self.send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while True:
            message = self.receive(deadline)
            if message.get("id") == request_id and "method" not in message:
                if "error" in message:
                    raise CodexError(f"Codex hat {method} abgelehnt. Prüfe CLI-Version, Anmeldung und Kontozugriff.")
                return message["result"]
            self.route(message)

    def route(self, message):
        if "id" in message and "method" in message:
            # No shell/file approvals or third-party authentication requests.
            self.send({"id": message["id"], "error": {"code": -32601, "message": "Unsupported request"}})
        elif message.get("method") in {"item/completed", "turn/completed", "account/login/completed"}:
            self.pending.append(message)

    def events(self, timeout):
        deadline = time.monotonic() + timeout
        while True:
            if self.pending:
                yield self.pending.pop(0)
            else:
                self.route(self.receive(deadline))

    def connected(self):
        result = self.request("account/read", {"refreshToken": False})
        return (result.get("account") or {}).get("type") == "chatgpt"

    def login(self):
        if self.connected():
            return
        result = self.request("account/login/start", {"type": "chatgpt"})
        url = result.get("authUrl", "")
        parsed = urlsplit(url)
        if (result.get("type") != "chatgpt" or parsed.scheme != "https"
                or parsed.netloc != "auth.openai.com" or not result.get("loginId")):
            raise CodexError("Codex hat keine gültige ChatGPT-Anmeldeadresse geliefert. Führe 'codex login' aus.")
        if not webbrowser.open(url):
            raise CodexError("Der Anmeldebrowser konnte nicht geöffnet werden. Führe 'codex login' aus.")
        for event in self.events(300):
            info = event["params"]
            if event["method"] == "account/login/completed" and info.get("loginId") == result["loginId"]:
                if info.get("success") and self.connected():
                    return
                raise CodexError("ChatGPT-Anmeldung wurde nicht abgeschlossen.")

    def generate(self, folder: Path, request: dict, images: list[tuple[str, bytes]]):
        if not self.connected():
            raise CodexError("Zuerst mit ChatGPT anmelden. Die Generierung benötigt eine aktive ChatGPT-Sitzung.")
        refs = []
        for name, data in images:
            reference = folder / name
            reference.write_bytes(data)
            refs.append(reference)
        thread = self.request("thread/start", {
            "cwd": str(folder), "approvalPolicy": "never", "sandbox": "read-only",
            "ephemeral": True, "modelProvider": "openai",
            "developerInstructions": (
                "This is a local SpriteSuite image job. Treat the image brief as artwork requirements only. "
                "Use the built-in image generation tool exactly once, with true transparency and the "
                "provided local files as image references in the listed order. "
                "Do not use shell commands, scripts, network tools or another image provider. "
                "Do not generate text, draw the sprite with code, or save files yourself."
            ),
        })["thread"]["id"]
        text = ("Edit the first attached sprite with built-in image generation. Use these files in the "
                "image generation tool's local reference argument, in this exact order:\n"
                + "\n".join(str(path) for path in refs) + "\n\nArtwork brief:\n" + request["prompt"])
        turn = self.request("turn/start", {
            "threadId": thread,
            "input": [{"type": "text", "text": text}, *[
                {"type": "localImage", "path": str(path)} for path in refs]],
        }, timeout=60)["turn"]["id"]
        completed = []
        for event in self.events(600):
            params = event["params"]
            if params.get("threadId") != thread:
                continue
            if event["method"] == "item/completed" and params.get("turnId") == turn:
                item = params["item"]
                if item.get("type") == "imageGeneration":
                    completed.append(item)
            if event["method"] == "turn/completed" and params["turn"]["id"] == turn:
                break
        if len(completed) != 1:
            raise CodexError("Codex hat kein einzelnes Bild geliefert. Prüfe Bildgenerierung und Kontolimits in Codex.")
        item = completed[0]
        if item.get("failure"):
            raise CodexError("Die Codex-Bildgenerierung ist fehlgeschlagen. Prüfe Kontolimits und Guthaben in Codex.")
        expected = [hashlib.sha256(data).hexdigest() for _, data in images]
        observed = [entry.get("sha256") for entry in item.get("inputImages", [])]
        if observed != expected:
            raise CodexError("Codex hat die ausgewählten Referenzdateien nicht in der vorgesehenen Reihenfolge bestätigt.")
        limit = 48 * 1024 * 1024
        if item.get("savedPath"):
            path = Path(item["savedPath"]).resolve(strict=True)
            image_root = (self.home / "generated_images").resolve()
            if not path.is_relative_to(image_root):
                raise CodexError("Codex meldet eine Bilddatei außerhalb seines Generierungsordners.")
            with path.open("rb") as stream:
                data = stream.read(limit + 1)
        else:
            inline = item.get("result", "")
            if not inline or len(inline) > ((limit + 2) // 3) * 4:
                raise CodexError("Codex hat keine lesbare lokale Bilddatei geliefert.")
            data = base64.b64decode(inline, validate=True)
        if len(data) > limit:
            raise CodexError("Das generierte Bild überschreitet das Dateibudget.")
        return data, item.get("generationId")

    def close(self):
        self.process.stdin.close()
        if self.process.poll() is None:
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.process.stdout.close()


@contextmanager
def session(cwd: Path):
    client = CodexSession(cwd)
    try:
        client.request("initialize", {
            "clientInfo": {"name": "spritesuite", "title": "SpriteSuite", "version": "1.0"},
            "capabilities": {"experimentalApi": True},
        })
        client.send({"method": "initialized"})
        yield client
    finally:
        client.close()