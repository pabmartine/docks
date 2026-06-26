import json
import socket
import time
from datetime import datetime
from http.client import HTTPResponse
from urllib.parse import quote

from ..core.i18n import translate as _
from ..models.connection import Connection
from ..models.container import Container
from ..models.image import Image
from ..models.network import Network
from ..models.volume import Volume


class DockerConnectionError(RuntimeError):
    pass


class DockerService:
    """Lightweight Docker API client for the local Unix socket."""

    def ping(self, connection: Connection) -> tuple[bool, str]:
        try:
            payload = self._request(connection, "GET", "/_ping")
        except DockerConnectionError as exc:
            return False, str(exc)

        if payload.decode("utf-8").strip() == "OK":
            return True, _("Connection available")
        return False, _("The local Docker daemon answered, but the ping was not valid.")

    def list_containers(self, connection: Connection) -> list[Container]:
        payload = self._request(connection, "GET", "/containers/json?all=1")
        items = json.loads(payload.decode("utf-8"))
        containers = []

        for item in items:
            names = item.get("Names") or []
            container_name = names[0].lstrip("/") if names else item.get("Id", "")[:12]
            labels = item.get("Labels") or {}
            containers.append(
                Container(
                    id=item.get("Id", ""),
                    name=container_name,
                    display_name=self._container_display_name(container_name, labels),
                    image=item.get("Image", "<unknown>"),
                    image_id=item.get("ImageID", ""),
                    status=self._normalize_container_status(item.get("State", item.get("Status", "unknown"))),
                    created_at=self._format_created_at(item.get("Created")),
                )
            )

        return containers

    def list_images(self, connection: Connection) -> list[Image]:
        payload = self._request(connection, "GET", "/images/json")
        items = json.loads(payload.decode("utf-8"))
        images = []

        for item in items:
            images.append(
                Image(
                    id=item.get("Id", "")[:19],
                    full_id=item.get("Id", ""),
                    tags=item.get("RepoTags") or [],
                    size=self._format_bytes(item.get("Size", 0)),
                    created_at=self._format_created_at(item.get("Created")),
                )
            )

        return images

    def list_volumes(self, connection: Connection) -> list[Volume]:
        payload = self._request(connection, "GET", "/volumes")
        items = json.loads(payload.decode("utf-8"))
        volumes = []

        for item in items.get("Volumes") or []:
            volumes.append(
                Volume(
                    name=item.get("Name", ""),
                    driver=item.get("Driver", "local"),
                    mountpoint=item.get("Mountpoint", ""),
                    created_at=self._format_created_at_string(item.get("CreatedAt")),
                )
            )

        return volumes

    def list_networks(self, connection: Connection) -> list[Network]:
        payload = self._request(connection, "GET", "/networks")
        items = json.loads(payload.decode("utf-8"))
        networks = []

        for item in items:
            ipv4, ipv6 = self._extract_network_subnets(item.get("IPAM", {}).get("Config") or [])
            labels = item.get("Labels") or {}
            networks.append(
                Network(
                    id=item.get("Id", ""),
                    name=item.get("Name", ""),
                    stack=labels.get("com.docker.compose.project")
                    or labels.get("com.docker.stack.namespace")
                    or "-",
                    driver=item.get("Driver", "bridge"),
                    ipv4=ipv4 or "-",
                    ipv6=ipv6 or "-",
                )
            )

        return networks

    def inspect_container(self, connection: Connection, container_id: str) -> dict:
        payload = self._request(connection, "GET", f"/containers/{container_id}/json")
        return json.loads(payload.decode("utf-8"))

    def inspect_image(self, connection: Connection, image_id: str) -> dict:
        payload = self._request(connection, "GET", f"/images/{image_id}/json")
        return json.loads(payload.decode("utf-8"))

    def inspect_volume(self, connection: Connection, volume_name: str) -> dict:
        payload = self._request(connection, "GET", f"/volumes/{volume_name}")
        return json.loads(payload.decode("utf-8"))

    def inspect_network(self, connection: Connection, network_id: str) -> dict:
        payload = self._request(connection, "GET", f"/networks/{network_id}")
        return json.loads(payload.decode("utf-8"))

    def start_container(self, connection: Connection, container_id: str) -> None:
        self._request(connection, "POST", f"/containers/{container_id}/start")

    def stop_container(self, connection: Connection, container_id: str) -> None:
        self._request(connection, "POST", f"/containers/{container_id}/stop")

    def restart_container(self, connection: Connection, container_id: str) -> None:
        self._request(connection, "POST", f"/containers/{container_id}/restart")

    def pause_container(self, connection: Connection, container_id: str) -> None:
        self._request(connection, "POST", f"/containers/{container_id}/pause")

    def unpause_container(self, connection: Connection, container_id: str) -> None:
        self._request(connection, "POST", f"/containers/{container_id}/unpause")

    def remove_container(self, connection: Connection, container_id: str, force: bool = True) -> None:
        force_flag = "1" if force else "0"
        self._request(connection, "DELETE", f"/containers/{container_id}?force={force_flag}")

    def remove_image(self, connection: Connection, image_id: str, force: bool = False) -> None:
        force_flag = "1" if force else "0"
        self._request(connection, "DELETE", f"/images/{image_id}?force={force_flag}")

    def remove_volume(self, connection: Connection, volume_name: str, force: bool = False) -> None:
        self._request(connection, "DELETE", f"/volumes/{volume_name}?force={'1' if force else '0'}")

    def remove_network(self, connection: Connection, network_id: str) -> None:
        self._request(connection, "DELETE", f"/networks/{network_id}")

    def container_logs(
        self,
        connection: Connection,
        container_id: str,
        tail: int = 200,
        since: int | None = None,
    ) -> str:
        if since is None:
            query = f"stdout=1&stderr=1&timestamps=1&tail={tail}"
        else:
            query = f"stdout=1&stderr=1&timestamps=1&since={since}"
        payload = self._request(
            connection,
            "GET",
            f"/containers/{container_id}/logs?{query}",
        )
        return self._decode_log_payload(payload)

    def pull_image(self, connection: Connection, image_ref: str) -> list[str]:
        if not image_ref.strip():
            raise DockerConnectionError(_("The image reference cannot be empty."))

        payload = self._request(
            connection,
            "POST",
            f"/images/create?fromImage={quote(image_ref.strip(), safe=':/@._-')}",
        )
        messages = []
        for line in payload.decode("utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                messages.append(line.strip())
                continue
            if item.get("error"):
                raise DockerConnectionError(item["error"])
            if item.get("status"):
                progress = item.get("progress")
                if progress:
                    messages.append(f"{item['status']} {progress}")
                else:
                    messages.append(item["status"])
        return messages

    def create_volume(self, connection: Connection, name: str, driver: str = "local") -> dict:
        if not name.strip():
            raise DockerConnectionError(_("The volume name cannot be empty."))
        payload = self._request_json(
            connection,
            "POST",
            "/volumes/create",
            {
                "Name": name.strip(),
                "Driver": driver.strip() or "local",
            },
        )
        return json.loads(payload.decode("utf-8"))

    def prune_images(self, connection: Connection) -> dict:
        payload = self._request(connection, "POST", "/images/prune")
        return json.loads(payload.decode("utf-8"))

    def prune_volumes(self, connection: Connection) -> dict:
        payload = self._request(connection, "POST", "/volumes/prune")
        return json.loads(payload.decode("utf-8"))

    def prune_networks(self, connection: Connection) -> dict:
        payload = self._request(connection, "POST", "/networks/prune")
        return json.loads(payload.decode("utf-8"))

    def create_network(
        self,
        connection: Connection,
        name: str,
        driver: str = "bridge",
        internal: bool = False,
        attachable: bool = False,
        enable_ipv6: bool = False,
    ) -> dict:
        if not name.strip():
            raise DockerConnectionError(_("The network name cannot be empty."))
        payload = self._request_json(
            connection,
            "POST",
            "/networks/create",
            {
                "Name": name.strip(),
                "Driver": driver.strip() or "bridge",
                "CheckDuplicate": True,
                "Internal": internal,
                "Attachable": attachable,
                "EnableIPv6": enable_ipv6,
            },
        )
        return json.loads(payload.decode("utf-8"))

    def create_container(
        self,
        connection: Connection,
        image_ref: str,
        name: str = "",
        command: str = "",
        start: bool = True,
    ) -> dict:
        if not image_ref.strip():
            raise DockerConnectionError(_("The container image cannot be empty."))

        body = {"Image": image_ref.strip()}
        if command.strip():
            body["Cmd"] = command.strip().split()

        path = "/containers/create"
        if name.strip():
            path = f"/containers/create?name={quote(name.strip(), safe='-._')}"

        payload = self._request_json(connection, "POST", path, body)
        response = json.loads(payload.decode("utf-8"))
        container_id = response.get("Id", "")
        if start and container_id:
            self.start_container(connection, container_id)
        return response

    def list_events(self, connection: Connection, since: int, until: int) -> list[dict]:
        payload = self._request(
            connection,
            "GET",
            f"/events?since={since}&until={until}",
        )
        events = []
        for line in payload.decode("utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return events

    def _request(self, connection: Connection, method: str, path: str) -> bytes:
        if not connection.uri.startswith("unix://"):
            raise DockerConnectionError(_("Only the local Docker Unix socket is supported right now."))

        socket_path = connection.uri.removeprefix("unix://")
        if not socket_path:
            raise DockerConnectionError(_("Docker socket path is empty."))

        try:
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.settimeout(3)
            client.connect(socket_path)
        except FileNotFoundError as exc:
            raise DockerConnectionError(
                _("Docker local socket was not found at %(path)s.") % {"path": socket_path}
            ) from exc
        except PermissionError as exc:
            raise DockerConnectionError(
                _("Permission denied while accessing %(path)s.") % {"path": socket_path}
            ) from exc
        except OSError as exc:
            raise DockerConnectionError(_("Could not connect to the local Docker socket.")) from exc

        encoded_path = quote(path, safe="/?=&,:-._")
        request = (
            f"{method} {encoded_path} HTTP/1.1\r\n"
            "Host: localhost\r\n"
            "User-Agent: docks/0.1\r\n"
            "Connection: close\r\n"
            "\r\n"
        )

        try:
            client.sendall(request.encode("utf-8"))
            response = HTTPResponse(_SocketReader(client))
            response.begin()
            body = response.read()
        except (OSError, ValueError) as exc:
            raise DockerConnectionError(_("The local Docker daemon did not answer correctly.")) from exc
        finally:
            client.close()

        if response.status >= 400:
            raise DockerConnectionError(
                _("Local Docker API returned HTTP %(status)s for %(path)s.") % {
                    "status": response.status,
                    "path": path,
                }
            )

        return body

    def _request_json(self, connection: Connection, method: str, path: str, payload: dict) -> bytes:
        encoded_body = json.dumps(payload).encode("utf-8")
        return self._request_with_body(
            connection,
            method,
            path,
            encoded_body,
            {
                "Content-Type": "application/json",
            },
        )

    def _request_with_body(
        self,
        connection: Connection,
        method: str,
        path: str,
        body: bytes,
        headers: dict[str, str] | None = None,
    ) -> bytes:
        if not connection.uri.startswith("unix://"):
            raise DockerConnectionError(_("Only the local Docker Unix socket is supported right now."))

        socket_path = connection.uri.removeprefix("unix://")
        if not socket_path:
            raise DockerConnectionError(_("Docker socket path is empty."))

        try:
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.settimeout(3)
            client.connect(socket_path)
        except FileNotFoundError as exc:
            raise DockerConnectionError(
                _("Docker local socket was not found at %(path)s.") % {"path": socket_path}
            ) from exc
        except PermissionError as exc:
            raise DockerConnectionError(
                _("Permission denied while accessing %(path)s.") % {"path": socket_path}
            ) from exc
        except OSError as exc:
            raise DockerConnectionError(_("Could not connect to the local Docker socket.")) from exc

        encoded_path = quote(path, safe="/?=&,:-._")
        header_lines = [
            f"{method} {encoded_path} HTTP/1.1",
            "Host: localhost",
            "User-Agent: docks/0.1",
            "Connection: close",
            f"Content-Length: {len(body)}",
        ]
        for key, value in (headers or {}).items():
            header_lines.append(f"{key}: {value}")
        request = "\r\n".join(header_lines).encode("utf-8") + b"\r\n\r\n" + body

        try:
            client.sendall(request)
            response = HTTPResponse(_SocketReader(client))
            response.begin()
            response_body = response.read()
        except (OSError, ValueError) as exc:
            raise DockerConnectionError(_("The local Docker daemon did not answer correctly.")) from exc
        finally:
            client.close()

        if response.status >= 400:
            raise DockerConnectionError(
                _("Local Docker API returned HTTP %(status)s for %(path)s.") % {
                    "status": response.status,
                    "path": path,
                }
            )

        return response_body

    def _format_bytes(self, value: int) -> str:
        size = float(value)
        units = ["B", "KB", "MB", "GB", "TB"]
        for unit in units:
            if size < 1024 or unit == units[-1]:
                if unit == "B":
                    return f"{int(size)} {unit}"
                return f"{size:.0f} {unit}"
            size /= 1024
        return f"{int(value)} B"

    def _normalize_container_status(self, state: str) -> str:
        if state == "exited":
            return "stopped"
        return state

    def _format_created_at(self, created: int | None) -> str:
        if not created:
            return _("Unknown")
        return datetime.fromtimestamp(created).strftime("%Y-%m-%d %H:%M")

    def _container_display_name(self, container_name: str, labels: dict[str, str]) -> str:
        for key in ("com.docker.compose.service", "app.kubernetes.io/name", "name"):
            value = labels.get(key)
            if value:
                return value
        return container_name

    def _format_created_at_string(self, value: str | None) -> str:
        if not value:
            return _("Unknown")
        normalized = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return value

    def _extract_network_subnets(self, config_list: list[dict]) -> tuple[str, str]:
        ipv4 = []
        ipv6 = []

        for item in config_list:
            subnet = item.get("Subnet")
            if not subnet:
                continue
            if ":" in subnet:
                ipv6.append(subnet)
            else:
                ipv4.append(subnet)

        return ", ".join(ipv4), ", ".join(ipv6)

    def _decode_log_payload(self, payload: bytes) -> str:
        if len(payload) < 8:
            return payload.decode("utf-8", errors="replace")

        decoded_chunks = []
        offset = 0

        try:
            while offset + 8 <= len(payload):
                stream_type = payload[offset]
                frame_size = int.from_bytes(payload[offset + 4:offset + 8], "big")
                if stream_type not in (1, 2) or frame_size < 0 or offset + 8 + frame_size > len(payload):
                    return payload.decode("utf-8", errors="replace")
                start = offset + 8
                end = start + frame_size
                decoded_chunks.append(payload[start:end].decode("utf-8", errors="replace"))
                offset = end
            if offset != len(payload):
                return payload.decode("utf-8", errors="replace")
            return "".join(decoded_chunks)
        except Exception:
            return payload.decode("utf-8", errors="replace")


class _SocketReader:
    def __init__(self, sock: socket.socket) -> None:
        self._file = sock.makefile("rb")

    def makefile(self, *_args, **_kwargs):
        return self._file
