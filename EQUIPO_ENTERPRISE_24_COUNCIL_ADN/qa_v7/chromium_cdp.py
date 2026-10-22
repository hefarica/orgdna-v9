"""Núcleo CDP (Chrome DevTools Protocol) en stdlib pura, sin dependencias externas.

Qué es
------
Cliente mínimo del protocolo CDP sobre WebSocket que permite conducir un Chromium
real (Chrome, Edge o Chromium) desde Python sin `selenium`, `playwright` ni
`websocket-client`. Cubre exactamente lo que el arnés E2E necesita: descubrir el
navegador, lanzarlo aislado, abrir un socket WebSocket RFC 6455 contra el endpoint
de depuración y hablar CDP con correlación de `id` y timeout.

Qué NO es
---------
- No sale a internet: todo el tráfico va a `127.0.0.1` (el host está fijado por
  constante y el puerto se valida antes de cada conexión).
- No instala, actualiza ni firma nada. Si no hay navegador, `find_chromium()`
  devuelve `None` y quien llama debe declararlo, no fingir que probó.
- No es un cliente WebSocket genérico: implementa sólo lo que CDP usa (texto,
  ping/pong, close, fragmentación). No negocia extensiones ni compresión.

Piezas públicas
---------------
- `find_chromium()` / `find_browser()` — localización multiplataforma.
- `launch(port, profile, headless)` — arranque con puerto de depuración propio y
  perfil temporal aislado; devuelve el **PID** (subclase de `int` con handles).
- `version(port)` — `GET /json/version` del endpoint de depuración.
- `targets(port)` — `GET /json/list`, para elegir una pestaña.
- `WebSocket` — cliente RFC 6455 mínimo (handshake, frames enmascarados de
  cliente, ping/pong, cierre limpio).
- `CDPSession` — sesión con `send(method, params)` e `id` correlado.
- `navigate`, `evaluate`, `screenshot`, `wait_for` — helpers de alto nivel.
- `terminate(handle)` — cierre del árbol de procesos y borrado del perfil.
- `profile_processes(profile)` — comprobación de que no quedan huérfanos.

Contrato de error: todo fallo del navegador o del protocolo se traduce a
`CDPError` (o sus subclases `CDPTimeout`, `CDPConnectionClosed`,
`ChromiumUnavailable`). No se propaga `socket.error` crudo al llamante.

Nota de plataforma: el cierre usa `taskkill /T /F` en Windows y `killpg` en
POSIX para tumbar también los procesos hijos de Chromium. `taskkill` es una
utilidad del sistema operativo, no una dependencia de Python.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import platform
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import uuid

__all__ = [
    'CDPError', 'CDPTimeout', 'CDPConnectionClosed', 'ChromiumUnavailable',
    'WebSocket', 'CDPSession', 'LaunchResult',
    'find_chromium', 'find_browser', 'launch', 'terminate', 'version', 'targets',
    'navigate', 'evaluate', 'screenshot', 'wait_for', 'dom_document',
    'profile_processes', 'free_port', 'self_test',
    'wait_active_port', 'new_profile_path', 'log_tail', 'wait_ready',
]

LOOPBACK = '127.0.0.1'
WS_GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
MAX_DISCOVERY_BYTES = 8 * 1024 * 1024
MAX_FRAME_BYTES = 64 * 1024 * 1024
OP_CONT, OP_TEXT, OP_BINARY, OP_CLOSE, OP_PING, OP_PONG = 0x0, 0x1, 0x2, 0x8, 0x9, 0xA


# --------------------------------------------------------------------------- #
# Errores
# --------------------------------------------------------------------------- #

class CDPError(RuntimeError):
    """Fallo del navegador o del protocolo CDP. Es el error base del módulo."""


class CDPTimeout(CDPError):
    """Se agotó un plazo esperando al navegador o a una respuesta CDP."""


class CDPConnectionClosed(CDPError):
    """El navegador cerró el WebSocket antes de responder."""


class ChromiumUnavailable(CDPError):
    """No hay navegador localizable, o el que existe no llegó a depurar."""


# --------------------------------------------------------------------------- #
# Localización del navegador
# --------------------------------------------------------------------------- #

def _windows_candidates():
    roots = []
    for var in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA', 'ProgramW6432'):
        value = os.environ.get(var)
        if value:
            roots.append(value)
    roots.append(r'C:\Program Files')
    roots.append(r'C:\Program Files (x86)')
    relative = (
        os.path.join(r'Google', 'Chrome', 'Application', 'chrome.exe'),
        os.path.join(r'Google', 'Chrome Beta', 'Application', 'chrome.exe'),
        os.path.join(r'Google', 'Chrome Dev', 'Application', 'chrome.exe'),
        os.path.join(r'Google', 'Chrome SxS', 'Application', 'chrome.exe'),
        os.path.join(r'Microsoft', 'Edge', 'Application', 'msedge.exe'),
        os.path.join(r'Chromium', 'Application', 'chrome.exe'),
        os.path.join(r'BraveSoftware', 'Brave-Browser', 'Application', 'brave.exe'),
    )
    found = []
    for root in roots:
        for tail in relative:
            found.append(os.path.join(root, tail))
    return found


def _posix_candidates(system):
    if system == 'Darwin':
        apps = [
            '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
            '/Applications/Chromium.app/Contents/MacOS/Chromium',
            '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
            '/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary',
        ]
        user = os.path.expanduser('~/Applications')
        apps.extend([
            os.path.join(user, 'Google Chrome.app', 'Contents', 'MacOS', 'Google Chrome'),
            os.path.join(user, 'Chromium.app', 'Contents', 'MacOS', 'Chromium'),
        ])
        return apps
    return [
        '/usr/bin/google-chrome', '/usr/bin/google-chrome-stable',
        '/usr/bin/chromium', '/usr/bin/chromium-browser',
        '/snap/bin/chromium', '/usr/lib/chromium/chromium',
        '/opt/google/chrome/chrome', '/usr/bin/microsoft-edge',
        '/opt/microsoft/msedge/msedge',
        '/usr/bin/brave-browser', '/opt/brave.com/brave/brave',
    ]


def _which(names):
    path = os.environ.get('PATH') or ''
    for name in names:
        for directory in path.split(os.pathsep):
            if not directory:
                continue
            candidate = os.path.join(directory, name)
            if os.path.isfile(candidate):
                return candidate
    return None


def find_browser(explicit=None):
    """Devuelve la ruta del primer navegador utilizable, o `None` con motivo.

    Orden de resolución: argumento explícito, `ORGDNA_CHROMIUM`, rutas estándar
    del sistema, y finalmente `PATH`. Nunca lanza: la ausencia de navegador es
    un estado declarable, no una excepción.
    """
    candidates = []
    for value, origin in ((explicit, 'explicit'), (os.environ.get('ORGDNA_CHROMIUM'), 'env:ORGDNA_CHROMIUM')):
        if value:
            candidates.append((os.path.expanduser(str(value)), origin))
    for path in _windows_candidates() if platform.system() == 'Windows' else _posix_candidates(platform.system()):
        candidates.append((path, 'standard'))
    for name in ('chrome', 'google-chrome', 'google-chrome-stable', 'chromium',
                 'chromium-browser', 'msedge', 'microsoft-edge', 'chrome.exe', 'msedge.exe'):
        path = _which([name])
        if path:
            candidates.append((path, 'PATH'))
    seen = set()
    for path, origin in candidates:
        if not path or path in seen:
            continue
        seen.add(path)
        if os.path.isfile(path):
            return {'path': path, 'origin': origin}
    return None


def find_chromium(explicit=None):
    """Ruta del navegador localizable, o `None` si no hay ninguno.

    Se mantiene como nombre histórico del contrato; `find_browser()` es el
    sinónimo que devuelve además el origen de la resolución.
    """
    found = find_browser(explicit)
    return found['path'] if found else None


# --------------------------------------------------------------------------- #
# Utilidades de red local (sólo 127.0.0.1)
# --------------------------------------------------------------------------- #

def _check_port(port):
    try:
        number = int(port)
    except (TypeError, ValueError):
        raise CDPError(f'Puerto de depuración no numérico: {port!r}') from None
    if not 0 < number < 65536:
        raise CDPError(f'Puerto de depuración fuera de rango: {number}')
    return number


def free_port():
    """Puerto TCP libre en 127.0.0.1 (se cierra antes de devolverlo)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((LOOPBACK, 0))
        return probe.getsockname()[1]


def _decode_chunked(payload):
    out, rest = [], payload
    while True:
        line, sep, rest = rest.partition(b'\r\n')
        if not sep:
            return b''.join(out)
        size_text = line.split(b';', 1)[0].strip()
        try:
            size = int(size_text, 16)
        except ValueError:
            return b''.join(out)
        if size == 0:
            return b''.join(out)
        out.append(rest[:size])
        rest = rest[size + 2:]


def _recv_more(sock, buffer, deadline, path, limit=MAX_DISCOVERY_BYTES):
    """Lee un bloque más del socket y lo acumula. Devuelve `None` en EOF."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise CDPTimeout(f'El descubrimiento en {path} agotó su plazo leyendo la respuesta.')
    sock.settimeout(max(0.05, remaining))
    block = sock.recv(65536)
    if not block:
        return None
    if len(buffer) + len(block) > limit:
        raise CDPError('Respuesta de descubrimiento demasiado grande.')
    return buffer + block


def _http_get(port, path, timeout=5.0):
    """GET mínimo por socket contra el endpoint de depuración local.

    Se evita `urllib.request` a propósito: no queremos que una variable de
    entorno de proxy pueda desviar una petición que debe quedarse en loopback.

    Detalle que importa: el servidor DevTools de Chrome **ignora**
    `Connection: close` y mantiene el socket abierto, así que esperar EOF
    equivale a esperar el timeout. La lectura se cierra por `Content-Length`
    (o por el terminador de `chunked`), nunca por cierre de conexión.
    """
    port = _check_port(port)
    if not path.startswith('/'):
        raise CDPError(f'Ruta de descubrimiento inválida: {path!r}')
    request = (
        f'GET {path} HTTP/1.1\r\n'
        f'Host: {LOOPBACK}:{port}\r\n'
        'Accept: application/json\r\n'
        'Connection: close\r\n\r\n'
    ).encode('ascii')
    deadline = time.monotonic() + float(timeout)
    raw = b''
    try:
        with socket.create_connection((LOOPBACK, port), timeout=float(timeout)) as sock:
            sock.sendall(request)
            while b'\r\n\r\n' not in raw:
                updated = _recv_more(sock, raw, deadline, path)
                if updated is None:
                    break
                raw = updated
            head, separator, body = raw.partition(b'\r\n\r\n')
            if not separator:
                raise CDPError('Respuesta de descubrimiento sin cabecera HTTP completa.')
            lines = head.split(b'\r\n')
            headers = {}
            for line in lines[1:]:
                name, _, value = line.partition(b':')
                headers[name.strip().lower()] = value.strip()
            chunked = headers.get(b'transfer-encoding', b'').lower() == b'chunked'
            length = None
            if not chunked and headers.get(b'content-length') is not None:
                try:
                    length = int(headers[b'content-length'])
                except ValueError:
                    length = None
            while True:
                if chunked:
                    if b'\r\n0\r\n\r\n' in body or body.endswith(b'0\r\n\r\n'):
                        break
                elif length is not None and len(body) >= length:
                    break
                try:
                    updated = _recv_more(sock, body, deadline, path)
                except CDPTimeout:
                    # Cuerpo incompleto: se declara el fallo, no se inventa.
                    if length is not None and len(body) < length:
                        raise
                    break
                if updated is None:
                    break
                body = updated
    except (socket.timeout, TimeoutError) as exc:
        raise CDPTimeout(f'El descubrimiento en {path} agotó {timeout}s: {exc}') from None
    except OSError as exc:
        raise CDPConnectionClosed(f'No se pudo conectar al endpoint local {port}: {exc}') from None
    try:
        status = int(lines[0].split(b' ')[1])
    except (IndexError, ValueError):
        raise CDPError(f'Línea de estado HTTP ilegible: {lines[0][:80]!r}') from None
    if chunked:
        body = _decode_chunked(body)
    elif length is not None:
        body = body[:length]
    return status, body


def _http_json(port, path, timeout=5.0):
    status, body = _http_get(port, path, timeout=timeout)
    if status != 200:
        raise CDPError(f'{path} devolvió HTTP {status} en el puerto {port}.')
    try:
        return json.loads(body.decode('utf-8'))
    except (UnicodeDecodeError, ValueError):
        raise CDPError(f'{path} no devolvió JSON válido.') from None


def version(port, timeout=5.0):
    """`GET /json/version`: identidad del navegador y endpoint WebSocket."""
    return _http_json(port, '/json/version', timeout=timeout)


def targets(port, timeout=5.0):
    """`GET /json/list`: pestañas y workers disponibles."""
    value = _http_json(port, '/json/list', timeout=timeout)
    if not isinstance(value, list):
        raise CDPError('/json/list no devolvió una lista de destinos.')
    return value


# --------------------------------------------------------------------------- #
# WebSocket RFC 6455 (cliente mínimo)
# --------------------------------------------------------------------------- #

def _mask(payload, key):
    if not payload:
        return b''
    repeated = (key * (len(payload) // 4 + 1))[:len(payload)]
    return bytes(a ^ b for a, b in zip(payload, repeated))


def _ws_path(value):
    """Ruta de recurso WebSocket a partir de una URL `ws://…` o de una ruta.

    `CDPSession.connect` recibe la URL que publica el navegador
    (`ws://127.0.0.1:PUERTO/devtools/page/…`); al handshake hay que enviarle
    sólo la ruta, nunca la URL completa (si no, el servidor responde 404).
    """
    text = str(value).strip()
    for scheme in ('ws://', 'wss://'):
        if text.lower().startswith(scheme):
            rest = text[len(scheme):]
            slash = rest.find('/')
            return rest[slash:] if slash >= 0 else '/'
    return text if text.startswith('/') else '/' + text


class WebSocket:
    """Cliente WebSocket mínimo para CDP: texto, ping/pong, cierre limpio.

    Implementa el lado cliente de RFC 6455 §4 (handshake) y §5 (frames): exige
    `Sec-WebSocket-Accept` correcto, enmascara **siempre** los frames salientes
    (obligatorio para clientes), acepta fragmentación entrante, responde `ping`
    con `pong` y realiza el cierre con código 1000. Cualquier violación del
    protocolo se reporta como `CDPError`.
    """

    def __init__(self, host, port, path, timeout=10.0):
        self.host = host
        self.port = _check_port(port)
        self.path = _ws_path(path)
        self.timeout = float(timeout)
        self._buffer = b''
        self._closed = False
        self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        try:
            self._handshake()
        except Exception:
            self._sock.close()
            raise

    # -- handshake ---------------------------------------------------------- #

    def _handshake(self):
        key = base64.b64encode(os.urandom(16)).decode('ascii')
        request = (
            f'GET {self.path} HTTP/1.1\r\n'
            f'Host: {self.host}:{self.port}\r\n'
            'Upgrade: websocket\r\n'
            'Connection: Upgrade\r\n'
            f'Sec-WebSocket-Key: {key}\r\n'
            'Sec-WebSocket-Version: 13\r\n\r\n'
        ).encode('ascii')
        self._sock.sendall(request)
        deadline = time.monotonic() + self.timeout
        while b'\r\n\r\n' not in self._buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CDPTimeout('El handshake WebSocket agotó su plazo.')
            self._sock.settimeout(max(0.05, remaining))
            try:
                block = self._sock.recv(65536)
            except (socket.timeout, TimeoutError):
                raise CDPTimeout('El handshake WebSocket agotó su plazo.') from None
            if not block:
                raise CDPConnectionClosed('El navegador cerró durante el handshake WebSocket.')
            self._buffer += block
            if len(self._buffer) > MAX_DISCOVERY_BYTES:
                raise CDPError('Handshake WebSocket demasiado grande.')
        head, _, self._buffer = self._buffer.partition(b'\r\n\r\n')
        lines = head.split(b'\r\n')
        try:
            status = int(lines[0].split(b' ')[1])
        except (IndexError, ValueError):
            raise CDPError(f'Línea de estado del handshake ilegible: {lines[0][:80]!r}') from None
        headers = {}
        for line in lines[1:]:
            name, _, value = line.partition(b':')
            headers[name.strip().lower()] = value.strip()
        if status != 101:
            raise CDPError(f'El handshake WebSocket devolvió HTTP {status}, se esperaba 101.')
        if headers.get(b'upgrade', b'').lower() != b'websocket':
            raise CDPError('El handshake no confirmó Upgrade: websocket.')
        expected = base64.b64encode(hashlib.sha1((key + WS_GUID).encode('ascii')).digest())
        if headers.get(b'sec-websocket-accept') != expected:
            raise CDPError('Sec-WebSocket-Accept no coincide con la clave enviada.')
        self.accept_verified = True

    # -- lectura ------------------------------------------------------------ #

    def _recv_exact(self, count, deadline):
        while len(self._buffer) < count:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CDPTimeout('Se agotó el plazo esperando un frame WebSocket.')
            self._sock.settimeout(max(0.05, remaining))
            try:
                block = self._sock.recv(65536)
            except (socket.timeout, TimeoutError):
                raise CDPTimeout('Se agotó el plazo esperando un frame WebSocket.') from None
            if not block:
                raise CDPConnectionClosed('El navegador cerró el WebSocket.')
            self._buffer += block
            if len(self._buffer) > MAX_FRAME_BYTES:
                raise CDPError('Frame WebSocket entrante demasiado grande.')
        head, self._buffer = self._buffer[:count], self._buffer[count:]
        return head

    def _read_frame(self, deadline):
        first, second = self._recv_exact(2, deadline)
        fin = bool(first & 0x80)
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        if length == 126:
            (length,) = struct.unpack('!H', self._recv_exact(2, deadline))
        elif length == 127:
            (length,) = struct.unpack('!Q', self._recv_exact(8, deadline))
        if length > MAX_FRAME_BYTES:
            raise CDPError(f'Frame WebSocket declarado de {length} bytes: rechazado.')
        key = self._recv_exact(4, deadline) if masked else b''
        payload = self._recv_exact(length, deadline) if length else b''
        if masked:
            payload = _mask(payload, key)
        return fin, opcode, payload

    def recv_message(self, timeout=None):
        """Devuelve el siguiente mensaje completo (`str` para texto, `bytes` binario)."""
        limit = self.timeout if timeout is None else float(timeout)
        deadline = time.monotonic() + limit
        parts, binary = [], False
        while True:
            fin, opcode, payload = self._read_frame(deadline)
            if opcode == OP_CLOSE:
                code = struct.unpack('!H', payload[:2])[0] if len(payload) >= 2 else None
                self._send_frame(OP_CLOSE, payload[:2])
                self._closed = True
                raise CDPConnectionClosed(f'El navegador cerró el WebSocket (code={code}).')
            if opcode == OP_PING:
                self._send_frame(OP_PONG, payload)
                continue
            if opcode == OP_PONG:
                continue
            if opcode in (OP_TEXT, OP_BINARY):
                parts, binary = [payload], opcode == OP_BINARY
            elif opcode == OP_CONT:
                if not parts:
                    raise CDPError('Frame de continuación sin mensaje previo.')
                parts.append(payload)
            else:
                raise CDPError(f'Opcode WebSocket no soportado: {opcode}')
            if fin:
                joined = b''.join(parts)
                return joined if binary else joined.decode('utf-8')

    # -- escritura ---------------------------------------------------------- #

    def _send_frame(self, opcode, payload=b'', fin=True):
        if self._closed and opcode != OP_CLOSE:
            raise CDPConnectionClosed('El WebSocket ya está cerrado.')
        mask_key = os.urandom(4)
        length = len(payload)
        header = bytearray([(0x80 if fin else 0) | opcode])
        if length < 126:
            header.append(0x80 | length)
        elif length < (1 << 16):
            header.append(0x80 | 126)
            header += struct.pack('!H', length)
        else:
            header.append(0x80 | 127)
            header += struct.pack('!Q', length)
        header += mask_key
        frame = bytes(header) + _mask(payload, mask_key)
        try:
            self._sock.sendall(frame)
        except OSError as exc:
            raise CDPConnectionClosed(f'No se pudo enviar el frame WebSocket: {exc}') from None

    def send_text(self, text):
        if not isinstance(text, str):
            raise CDPError('send_text espera una cadena.')
        self._send_frame(OP_TEXT, text.encode('utf-8'))

    def close(self, code=1000, reason='cierre local'):
        """Cierre limpio: frame `close` enmascarado y cierre del socket."""
        if self._closed:
            return
        try:
            payload = struct.pack('!H', int(code)) + str(reason).encode('utf-8')[:120]
            self._send_frame(OP_CLOSE, payload)
        except CDPError:
            pass
        finally:
            self._closed = True
            try:
                self._sock.close()
            except OSError:
                pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


# --------------------------------------------------------------------------- #
# Sesión CDP
# --------------------------------------------------------------------------- #

class CDPSession:
    """Sesión CDP sobre un WebSocket: `send()` con `id` correlado y timeout."""

    def __init__(self, ws, target=None, timeout=20.0):
        self.ws = ws
        self.target = target or {}
        self.timeout = float(timeout)
        self._next_id = 0
        self.events = []
        self.operations = 0

    @property
    def target_id(self):
        return self.target.get('id')

    @property
    def websocket_url(self):
        return self.target.get('webSocketDebuggerUrl')

    @classmethod
    def connect(cls, port, target_filter='page', timeout=20.0, index=0):
        """Conecta a la primera pestaña (o al tipo indicado) del puerto dado."""
        found = targets(port, timeout=timeout)
        pages = [item for item in found if item.get('webSocketDebuggerUrl')]
        if target_filter:
            pages = [item for item in pages if item.get('type') == target_filter]
        if not pages:
            raise CDPError(f'No hay destinos de tipo {target_filter!r} en el puerto {port}.')
        try:
            chosen = pages[int(index)]
        except IndexError:
            raise CDPError(f'Sólo hay {len(pages)} destinos; se pidió el índice {index}.') from None
        ws = WebSocket(LOOPBACK, port, chosen['webSocketDebuggerUrl'], timeout=timeout)
        return cls(ws, target=chosen, timeout=timeout)

    @classmethod
    def connect_browser(cls, port, timeout=20.0):
        """Conecta al endpoint del navegador (`/json/version`)."""
        info = version(port, timeout=timeout)
        url = info.get('webSocketDebuggerUrl')
        if not url:
            raise CDPError('El endpoint de versión no expone webSocketDebuggerUrl.')
        ws = WebSocket(LOOPBACK, port, url, timeout=timeout)
        return cls(ws, target={'type': 'browser', 'webSocketDebuggerUrl': url}, timeout=timeout)

    def send(self, method, params=None, timeout=None):
        """Envía `method` y espera el mensaje con el `id` correspondiente."""
        limit = self.timeout if timeout is None else float(timeout)
        deadline = time.monotonic() + limit
        self._next_id += 1
        message_id = self._next_id
        payload = {'id': message_id, 'method': method, 'params': dict(params or {})}
        self.ws.send_text(json.dumps(payload, ensure_ascii=False))
        self.operations += 1
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CDPTimeout(f'{method} agotó {limit}s esperando respuesta CDP.')
            message = self.ws.recv_message(timeout=remaining)
            if not isinstance(message, str):
                raise CDPError('CDP recibió un mensaje binario inesperado.')
            try:
                decoded = json.loads(message)
            except ValueError:
                raise CDPError('CDP recibió un mensaje que no es JSON.') from None
            if decoded.get('id') == message_id:
                if 'error' in decoded:
                    error = decoded.get('error') or {}
                    raise CDPError(f'{method} falló: {error.get("message", error)} (code={error.get("code")})')
                return decoded.get('result', {})
            # Evento del dominio (sin id): se conserva para diagnóstico acotado.
            self.events.append(decoded)
            if len(self.events) > 256:
                del self.events[:128]

    # -- helpers de dominio -------------------------------------------------- #

    def evaluate(self, expression, return_by_value=True, await_promise=True, timeout=None):
        """`Runtime.evaluate`. Con `return_by_value` devuelve el valor Python."""
        result = self.send('Runtime.evaluate', {
            'expression': str(expression),
            'returnByValue': bool(return_by_value),
            'awaitPromise': bool(await_promise),
            'userGesture': False,
            'includeCommandLineAPI': False,
        }, timeout=timeout)
        if result.get('exceptionDetails'):
            detail = result['exceptionDetails']
            text = (detail.get('exception') or {}).get('description') or detail.get('text') or 'excepción'
            raise CDPError(f'Runtime.evaluate lanzó una excepción: {str(text)[:300]}')
        remote = result.get('result') or {}
        return remote.get('value') if return_by_value else remote

    def dom_document(self, depth=1, timeout=None):
        """`DOM.getDocument`: raíz del documento con profundidad acotada."""
        result = self.send('DOM.getDocument', {'depth': int(depth), 'pierce': False}, timeout=timeout)
        root = result.get('root')
        if not isinstance(root, dict):
            raise CDPError('DOM.getDocument no devolvió una raíz de documento.')
        return root

    def enable(self, domain):
        """Habilita un dominio CDP; devuelve False si el navegador no lo expone."""
        try:
            self.send(f'{domain}.enable', {})
            return True
        except CDPError:
            return False

    def close(self):
        try:
            self.ws.close()
        except CDPError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


# --------------------------------------------------------------------------- #
# Lanzamiento y cierre del navegador
# --------------------------------------------------------------------------- #

class LaunchResult(int):
    """PID del navegador lanzado, con los handles necesarios para cerrarlo.

    Es un `int` de verdad (`pid = launch(); isinstance(pid, int)`), de modo que
    el contrato «devuelve el PID» se cumple literalmente, y además expone los
    objetos que `terminate()` necesita para no dejar huérfanos.
    """

    def __new__(cls, pid, process=None, port=None, profile=None, binary=None,
                created_profile=False, started_at=None, version_info=None,
                launcher_pid=None, browser_pids=None, log_path=None):
        obj = super().__new__(cls, int(pid))
        obj.process = process
        obj.port = port
        obj.profile = profile
        obj.binary = binary
        obj.created_profile = bool(created_profile)
        obj.started_at = started_at
        obj.version_info = version_info or {}
        obj.launcher_pid = int(launcher_pid) if launcher_pid else int(pid)
        obj.browser_pids = list(browser_pids or [])
        obj.log_path = log_path
        return obj

    @property
    def pid(self):
        return int(self)

    @property
    def endpoint(self):
        return f'http://{LOOPBACK}:{self.port}'

    def alive(self):
        """True si el navegador (no el lanzador) sigue vivo con nuestro perfil."""
        if self.profile:
            found = profile_processes(self.profile)
            if found.get('checked'):
                return bool(found.get('pids'))
        return self.process is not None and self.process.poll() is None

    def as_dict(self):
        return {
            'pid': self.pid, 'port': self.port, 'endpoint': self.endpoint,
            'profile': self.profile, 'binary': self.binary,
            'created_profile': self.created_profile,
            'launcher_pid': self.launcher_pid, 'browser_pids': list(self.browser_pids),
            'log_path': self.log_path,
            'browser': self.version_info.get('Browser'),
            'protocol_version': self.version_info.get('Protocol-Version'),
        }


def _launch_args(binary, port, profile, headless, extra_args, url='about:blank'):
    args = [
        binary,
        f'--remote-debugging-port={int(port)}',
        f'--user-data-dir={profile}',
        '--no-first-run',
        '--no-default-browser-check',
        '--disable-extensions',
        '--disable-default-apps',
        '--disable-sync',
        '--disable-component-update',
        '--disable-background-networking',
        '--disable-background-timer-throttling',
        '--disable-renderer-backgrounding',
        '--metrics-recording-only',
        '--mute-audio',
        '--hide-scrollbars',
        '--window-size=1280,900',
    ]
    if headless:
        args.append('--headless=new')
        args.append('--disable-gpu')
    args.append(str(url) if url else 'about:blank')
    args.extend(str(item) for item in (extra_args or ()))
    return args


def new_profile_path():
    """Ruta de perfil **plana y aún inexistente** bajo el directorio temporal.

    Dos detalles medidos en este host, no supuestos: Chrome 155 sale con código
    0 sin arrancar si `--user-data-dir` ya existe vacío, y también si la ruta
    está anidada bajo un directorio recién creado. La ruta plana e inexistente
    es la única que arranca de forma fiable; Chrome crea el directorio.
    """
    return os.path.join(tempfile.gettempdir(), 'orgdna-chromium-' + uuid.uuid4().hex)


def wait_active_port(profile, process=None, timeout=30.0, interval=0.05):
    """Espera `<perfil>/DevToolsActivePort` y devuelve el puerto real.

    Evita por completo la carrera de elegir un puerto libre y rezarlo: el
    navegador elige el puerto, lo escribe en su perfil y aquí se lee. La primera
    línea es el puerto y la segunda la ruta WebSocket del endpoint de navegador.
    """
    path = os.path.join(profile, 'DevToolsActivePort')
    deadline = time.monotonic() + float(timeout)
    while time.monotonic() < deadline:
        if process is not None and process.poll() not in (None, 0):
            raise ChromiumUnavailable(
                f'El navegador terminó con código {process.returncode} antes de publicar el puerto de depuración.')
        if os.path.exists(path):
            try:
                with open(path, encoding='utf-8', errors='replace') as stream:
                    lines = [line.strip() for line in stream.read().splitlines() if line.strip()]
            except OSError:
                lines = []
            if lines and lines[0].isdigit():
                return int(lines[0])
        time.sleep(interval)
    raise CDPTimeout(
        f'El navegador no publicó DevToolsActivePort en {timeout}s (perfil {profile}).')


def launch(port=None, profile=None, headless=True, binary=None, timeout=30.0, extra_args=None, url='about:blank'):
    """Arranca el navegador con depuración propia y perfil aislado.

    Estrategia de puerto: por omisión se pasa `--remote-debugging-port=0` y se
    lee el puerto real de `<perfil>/DevToolsActivePort`; así no existe carrera
    entre elegir un puerto y que otro proceso lo tome. Si se pasa un `port`
    explícito, se usa ese y se comprueba su endpoint.

    Devuelve un `LaunchResult` (que **es** el PID) cuando el endpoint de
    depuración ya responde. Si el navegador no existe, lanza
    `ChromiumUnavailable`; si no llega a depurar en `timeout`, se cierra lo
    arrancado y se lanza `CDPTimeout` con la cola del stderr de Chrome (nunca se
    deja el proceso vivo ni se oculta el motivo).
    """
    found = find_browser(binary)
    if not found:
        raise ChromiumUnavailable(
            'No se localizó Chrome/Chromium/Edge. Define ORGDNA_CHROMIUM con la ruta del ejecutable.')
    binary = found['path']
    created_profile = not profile
    if created_profile:
        profile = new_profile_path()
    else:
        profile = os.path.abspath(profile)
    requested_port = 0 if not port else _check_port(port)
    log_path = profile + '.stderr.log'
    args = _launch_args(binary, requested_port, profile, headless, extra_args, url=url)
    popen_kwargs = {}
    if os.name == 'nt':
        popen_kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    else:
        popen_kwargs['start_new_session'] = True
    started_at = time.time()
    try:
        log_stream = open(log_path, 'wb')
    except OSError:
        log_stream = subprocess.DEVNULL
    try:
        process = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            close_fds=True,
            **popen_kwargs,
        )
    except OSError as exc:
        if hasattr(log_stream, 'close'):
            log_stream.close()
        shutil.rmtree(profile, ignore_errors=True)
        raise ChromiumUnavailable(f'No se pudo ejecutar {binary}: {exc}') from None
    finally:
        if hasattr(log_stream, 'close') and log_stream is not subprocess.DEVNULL:
            try:
                log_stream.close()
            except OSError:
                pass
    launcher = LaunchResult(process.pid, process=process, port=requested_port, profile=profile,
                            binary=binary, created_profile=created_profile, started_at=started_at,
                            log_path=log_path)
    try:
        if requested_port:
            resolved = requested_port
            info = wait_ready(resolved, process=process, timeout=timeout)
        else:
            resolved = wait_active_port(profile, process=process, timeout=timeout)
            info = wait_ready(resolved, process=process, timeout=15.0)
    except CDPError as exc:
        tail = log_tail(log_path)
        terminate(launcher)
        detail = f' | Chrome stderr (cola): {tail}' if tail else ' | Chrome no escribió stderr.'
        raise type(exc)(f'{exc}{detail}') from None
    found_pids = profile_processes(profile)
    top_level = list(found_pids.get('top_level_pids') or [])
    # Chrome re-ejecuta el lanzador y el navegador real es otro proceso: el PID
    # devuelto es el del navegador cuando se resuelve sin ambigüedad.
    effective_pid = top_level[0] if len(top_level) == 1 else process.pid
    return LaunchResult(effective_pid, process=process, port=resolved, profile=profile,
                        binary=binary, created_profile=created_profile, started_at=started_at,
                        version_info=info, launcher_pid=process.pid,
                        browser_pids=top_level or [process.pid], log_path=log_path)


def log_tail(path, lines=12, limit=2000):
    """Últimas líneas del log de Chrome, para no perder el motivo de un fallo."""
    try:
        with open(path, 'rb') as stream:
            data = stream.read(65536)
    except OSError:
        return ''
    text = data.decode('utf-8', 'replace').strip()
    if not text:
        return ''
    tail = '\n'.join(text.splitlines()[-lines:])
    # Nunca se propaga el carácter de reemplazo: rompe consolas cp1252.
    return tail.replace('\ufffd', '?')[-limit:]


def wait_ready(port, process=None, timeout=25.0, interval=0.05):
    """Espera a que `/json/version` responda; devuelve su JSON.

    Chrome en Windows puede re-ejecutarse: el proceso lanzado termina con
    código 0 mientras el navegador real (otro PID) sigue arrancando. Por eso una
    salida 0 del lanzador **no** es un fallo; sólo lo es una salida distinta de
    cero, que indica que el binario se negó a arrancar.
    """
    deadline = time.monotonic() + float(timeout)
    last = None
    while time.monotonic() < deadline:
        if process is not None and process.poll() not in (None, 0):
            raise ChromiumUnavailable(
                f'El navegador terminó con código {process.returncode} antes de depurar en el puerto {port}.')
        try:
            return version(port, timeout=min(2.0, max(0.2, deadline - time.monotonic())))
        except CDPError as exc:
            last = exc
            time.sleep(interval)
    raise CDPTimeout(f'El endpoint de depuración del puerto {port} no respondió en {timeout}s (último: {last}).')


def _taskkill_tree(pid, timeout=15.0):
    """Mata el árbol de procesos en Windows; devuelve (ok, detalle)."""
    command = ['taskkill', '/PID', str(int(pid)), '/T', '/F']
    try:
        completed = subprocess.run(command, capture_output=True, timeout=timeout,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f'taskkill no pudo ejecutarse: {exc}'
    detail = (completed.stdout or b'').decode('utf-8', 'replace').strip()
    if completed.returncode != 0:
        error = (completed.stderr or b'').decode('utf-8', 'replace').strip()
        return False, f'taskkill rc={completed.returncode}: {error or detail}'
    return True, detail


def _terminate_pid(pid, timeout=15.0):
    """Termina un proceso y su descendencia. Devuelve (ok, detalle).

    Windows: `taskkill /T /F` (árbol completo). POSIX: `killpg` sobre el grupo
    si el proceso es líder, y `SIGTERM`/`SIGKILL` directo en caso contrario.
    """
    if os.name == 'nt':
        return _taskkill_tree(pid, timeout)
    import signal  # local: sólo POSIX lo necesita
    try:
        group = os.getpgid(int(pid))
    except OSError:
        group = None
    try:
        if group is not None and group == int(pid):
            os.killpg(group, signal.SIGTERM)
        else:
            os.kill(int(pid), signal.SIGTERM)
    except OSError as exc:
        return False, f'SIGTERM falló: {exc}'
    deadline = time.monotonic() + float(timeout)
    while time.monotonic() < deadline:
        try:
            os.kill(int(pid), 0)
        except OSError:
            return True, 'proceso terminado con SIGTERM'
        time.sleep(0.05)
    try:
        if group is not None and group == int(pid):
            os.killpg(group, signal.SIGKILL)
        else:
            os.kill(int(pid), signal.SIGKILL)
        return True, 'proceso terminado con SIGKILL'
    except OSError as exc:
        return False, f'SIGKILL falló: {exc}'


def profile_processes(profile, timeout=15.0):
    """Procesos de navegador vivos que aún usan `profile` como `--user-data-dir`.

    Devuelve `{'checked': bool, 'pids': [...], 'top_level_pids': [...],
    'reason': str}`. `top_level_pids` son los procesos sin `--type=`, es decir
    los procesos de navegador (los demás son renderers/GPU/utilidades). Si la
    consulta del sistema no está disponible se declara `checked: False` con el
    motivo: no se finge que no hay huérfanos.
    """
    wanted = os.path.abspath(str(profile)).lower() if os.name == 'nt' else os.path.abspath(str(profile))
    if not wanted:
        return {'checked': False, 'pids': [], 'top_level_pids': [], 'reason': 'perfil vacío'}
    if platform.system() == 'Windows':
        script = (
            "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe' OR Name='msedge.exe' "
            "OR Name='chromium.exe' OR Name='brave.exe'\" | ForEach-Object { "
            "\"$($_.ProcessId)`t$($_.CommandLine)\" }"
        )
        command = ['powershell', '-NoProfile', '-NonInteractive', '-Command', script]
    else:
        command = ['ps', '-eo', 'pid=,command=']
    try:
        completed = subprocess.run(command, capture_output=True, timeout=timeout,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.SubprocessError) as exc:
        return {'checked': False, 'pids': [], 'top_level_pids': [],
                'reason': f'consulta de procesos no disponible: {exc}'}
    text = (completed.stdout or b'').decode('utf-8', 'replace')
    pids, top_level = [], []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        pid_text, _, tail = stripped.partition('\t') if '\t' in stripped else stripped.partition(' ')
        if wanted not in tail.lower() and wanted not in stripped.lower():
            continue
        try:
            number = int(pid_text.strip())
        except ValueError:
            continue
        pids.append(number)
        if '--type=' not in tail:
            top_level.append(number)
    return {'checked': True, 'pids': sorted(set(pids)),
            'top_level_pids': sorted(set(top_level)), 'reason': ''}


def terminate(handle, keep_profile=False, timeout=20.0, kill_timeout=15.0):
    """Cierra el árbol de procesos del navegador y borra el perfil temporal.

    Idempotente y seguro sobre un `LaunchResult` ya cerrado. Devuelve un dict
    con `exited`, `killed_tree`, `profile_removed` y `orphans`, de modo que el
    llamante pueda demostrar limpieza en vez de afirmarla.
    """
    report = {
        'pid': int(handle) if handle is not None else None,
        'exited': True, 'killed_tree': None, 'exit_code': None,
        'profile': getattr(handle, 'profile', None), 'profile_removed': None,
        'log_removed': None,
        'orphans': {'checked': False, 'pids': [], 'reason': 'no consultado'},
    }
    if handle is None:
        return report
    process = getattr(handle, 'process', None)
    profile = getattr(handle, 'profile', None)
    actions = []
    if process is not None and process.poll() is None:
        ok, detail = _terminate_pid(process.pid, kill_timeout)
        actions.append({'target': 'launcher', 'pid': process.pid, 'ok': ok, 'detail': detail})
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except OSError:
                pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
    if process is not None:
        report['exit_code'] = process.returncode
    # El navegador efectivo puede ser otro proceso (Chrome re-ejecuta el
    # lanzador). Se cierra por identidad de perfil hasta que no quede ninguno.
    remaining = []
    deadline = time.monotonic() + float(kill_timeout)
    while True:
        found = profile_processes(profile) if profile else {'checked': False, 'pids': [], 'top_level_pids': []}
        remaining = list(found.get('pids') or [])
        if not remaining or time.monotonic() >= deadline:
            break
        targets = list(found.get('top_level_pids') or []) or remaining
        for pid in targets:
            ok, detail = _terminate_pid(pid, kill_timeout)
            actions.append({'target': 'browser', 'pid': pid, 'ok': ok, 'detail': detail})
        time.sleep(0.25)
    report['killed_tree'] = actions
    report['exited'] = not remaining
    # La comprobación final por perfil es la autoritativa: `taskkill` devuelve
    # error cuando un hijo ya había muerto por la caída del padre, y eso no es
    # un huérfano. Se declara explícitamente en vez de maquillar cada acción.
    report['tree_cleared'] = not remaining
    if not remaining:
        for action in actions:
            action['resolved'] = True
    if profile:
        final = profile_processes(profile)
        report['orphans'] = final
        if not keep_profile and getattr(handle, 'created_profile', False):
            removed = False
            for attempt in range(8):
                shutil.rmtree(profile, ignore_errors=True)
                if not os.path.exists(profile):
                    removed = True
                    break
                time.sleep(0.15 * (attempt + 1))
            report['profile_removed'] = removed
        else:
            report['profile_removed'] = None if keep_profile else not os.path.exists(profile)
    log_path = getattr(handle, 'log_path', None)
    if log_path and getattr(handle, 'created_profile', False) and not keep_profile:
        try:
            os.remove(log_path)
        except OSError:
            pass
        report['log_removed'] = not os.path.exists(log_path)
    return report


# --------------------------------------------------------------------------- #
# Helpers de alto nivel
# --------------------------------------------------------------------------- #

def navigate(session, url, timeout=20.0, wait=True):
    """`Page.navigate` y, por omisión, espera a `document.readyState == complete`."""
    result = session.send('Page.navigate', {'url': str(url)}, timeout=timeout)
    if result.get('errorText'):
        raise CDPError(f'Page.navigate rechazó {url!r}: {result["errorText"]}')
    if wait:
        wait_for(session, "document.readyState === 'complete'", timeout=timeout)
    return result


def evaluate(session, expression, return_by_value=True, timeout=None):
    """Atajo de `Runtime.evaluate` con retorno por valor."""
    return session.evaluate(expression, return_by_value=return_by_value, timeout=timeout)


def dom_document(session, depth=1, timeout=None):
    """Atajo de `DOM.getDocument`."""
    return session.dom_document(depth=depth, timeout=timeout)


def wait_for(session, predicate_js, timeout=15.0, interval=0.1):
    """Espera a que `predicate_js` sea verdadero en la página.

    Reintenta ante errores transitorios de contexto (una navegación destruye el
    contexto de ejecución y `Runtime.evaluate` falla una o dos veces). Si el
    plazo se agota, lanza `CDPTimeout` con el último valor observado.
    """
    deadline = time.monotonic() + float(timeout)
    last = None
    while time.monotonic() < deadline:
        try:
            value = session.evaluate(predicate_js, return_by_value=True)
            if value:
                return value
            last = value
        except (CDPError, CDPTimeout, CDPConnectionClosed) as exc:
            last = f'{type(exc).__name__}: {exc}'
        time.sleep(interval)
    raise CDPTimeout(f'wait_for agotó {timeout}s esperando {predicate_js!r} (último: {last!r})')


def screenshot(session, path, timeout=25.0):
    """`Page.captureScreenshot` a PNG verificado por bytes mágicos."""
    result = session.send('Page.captureScreenshot',
                          {'format': 'png', 'captureBeyondViewport': False}, timeout=timeout)
    encoded = result.get('data')
    if not encoded:
        raise CDPError('Page.captureScreenshot no devolvió datos.')
    try:
        raw = base64.b64decode(encoded)
    except (ValueError, TypeError):
        raise CDPError('La captura no es base64 válido.') from None
    if not raw.startswith(b'\x89PNG\r\n\x1a\n'):
        raise CDPError('La captura no empieza con la firma PNG esperada.')
    destination = os.path.abspath(os.path.expanduser(str(path)))
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    with open(destination, 'wb') as stream:
        stream.write(raw)
    return {'path': destination, 'bytes': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest()}


# --------------------------------------------------------------------------- #
# Autoprueba del núcleo
# --------------------------------------------------------------------------- #

def self_test(screenshot_dir=None, keep_profile=False):
    """Comprueba el núcleo contra un navegador real sin depender del panel.

    Ejercita el ciclo completo: lanzamiento con perfil temporal, handshake
    WebSocket con `Sec-WebSocket-Accept` verificado, `Page.navigate` a una
    página `data:`, lectura del DOM por `Runtime.evaluate`, `DOM.getDocument`,
    captura PNG y cierre con verificación de huérfanos.
    """
    report = {'available': False, 'steps': [], 'available_reason': '', 'cleanup': None}
    found = find_browser()
    if not found:
        report['available_reason'] = ('chromium_unavailable: no se localizó Chrome, Chromium ni Edge '
                                      'en rutas estándar ni en ORGDNA_CHROMIUM')
        return report
    report['available'] = True
    report['browser'] = found
    handle = None
    session = None
    destination = screenshot_dir or os.path.join(tempfile.gettempdir(), 'orgdna_cdp')
    try:
        handle = launch(port=0, profile=None, headless=True)
        report['steps'].append({'step': 'launch', 'ok': True, 'pid': handle.pid,
                                'port': handle.port, 'browser_version': handle.version_info.get('Browser')})
        session = CDPSession.connect(handle.port, target_filter='page')
        report['steps'].append({'step': 'websocket_handshake', 'ok': True,
                                'accept_verified': getattr(session.ws, 'accept_verified', False)})
        session.enable('Page')
        session.enable('Runtime')
        page = ('data:text/html;charset=utf-8,'
                '<!doctype html><html><head><title>OrgDNA CDP self test</title></head>'
                '<body><h1 id="value">orgdna-cdp-ok</h1></body></html>')
        navigate(session, page, timeout=25.0)
        report['steps'].append({'step': 'Page.navigate', 'ok': True})
        title = evaluate(session, 'document.title')
        text = evaluate(session, "document.getElementById('value').textContent")
        report['steps'].append({'step': 'Runtime.evaluate', 'ok': title == 'OrgDNA CDP self test' and text == 'orgdna-cdp-ok',
                                'title': title, 'value': text})
        root = dom_document(session, depth=1)
        report['steps'].append({'step': 'DOM.getDocument', 'ok': bool(root.get('nodeName')),
                                'node_name': root.get('nodeName'),
                                'child_count': root.get('childNodeCount')})
        capture = screenshot(session, os.path.join(destination, 'cdp_self_test.png'))
        report['steps'].append({'step': 'Page.captureScreenshot', 'ok': capture['bytes'] > 0,
                                'path': capture['path'], 'bytes': capture['bytes'],
                                'sha256': capture['sha256']})
    except CDPError as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        if session is not None:
            session.close()
        report['cleanup'] = terminate(handle, keep_profile=keep_profile)
    return report


def main(argv=None):
    # La salida JSON incluye rutas y diagnósticos: se emite en UTF-8 aunque la
    # consola del host sea cp1252 (misma lección que la línea base de encoding).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(
        description='Núcleo CDP en stdlib: localiza el navegador y comprueba el protocolo contra un Chromium real.')
    parser.add_argument('--self-test', action='store_true',
                        help='lanza un navegador headless y ejercita navigate/evaluate/DOM/screenshot.')
    parser.add_argument('--screenshot-dir', default=None, help='Directorio de la captura de autoprueba.')
    parser.add_argument('--keep-profile', action='store_true', help='No borrar el perfil temporal (diagnóstico).')
    parser.add_argument('--version', action='store_true', help='Sólo informar de la ruta y la versión detectadas.')
    args = parser.parse_args(argv)
    start = time.time()
    if args.version:
        found = find_browser()
        payload = {'found': bool(found), 'browser': found,
                   'available_reason': '' if found else 'chromium_unavailable'}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if not args.self_test:
        parser.print_help()
        return 0
    report = self_test(screenshot_dir=args.screenshot_dir, keep_profile=args.keep_profile)
    report['duration_s'] = round(time.time() - start, 3)
    if not report['available']:
        print(json.dumps({'chromium_unavailable': True, 'reason': report['available_reason']},
                         ensure_ascii=False, indent=2))
        return 0
    failed = [step for step in report['steps'] if not step.get('ok')]
    cleanup = report.get('cleanup') or {}
    orphans = (cleanup.get('orphans') or {}).get('pids') or []
    report['ok'] = bool(report['steps']) and not failed and not report.get('error') and not orphans
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
