import unittest
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from docks.models.connection import Connection
from docks.services.docker_service import DockerConnectionError, DockerService


class DockerServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = DockerService()

    def test_decode_log_payload_handles_framed_stdout(self) -> None:
        chunk = b"hello\n"
        payload = bytes([1, 0, 0, 0]) + len(chunk).to_bytes(4, "big") + chunk
        self.assertEqual(self.service._decode_log_payload(payload), "hello\n")

    def test_extract_network_subnets_splits_ipv4_and_ipv6(self) -> None:
        ipv4, ipv6 = self.service._extract_network_subnets(
            [
                {"Subnet": "172.18.0.0/16"},
                {"Subnet": "fd00::/64"},
            ]
        )
        self.assertEqual(ipv4, "172.18.0.0/16")
        self.assertEqual(ipv6, "fd00::/64")

    def test_normalize_container_status_maps_exited_to_stopped(self) -> None:
        self.assertEqual(self.service._normalize_container_status("exited"), "stopped")
        self.assertEqual(self.service._normalize_container_status("running"), "running")

    def test_request_uses_configured_socket_path_in_errors(self) -> None:
        connection = Connection("custom", "Custom", "unix:///tmp/docker-test.sock")
        with patch("docks.services.docker_service.socket.socket") as socket_factory:
            socket_factory.return_value.connect.side_effect = FileNotFoundError()
            with self.assertRaises(DockerConnectionError) as exc:
                self.service._request(connection, "GET", "/_ping")
        self.assertIn("/tmp/docker-test.sock", str(exc.exception))

    def test_pull_image_raises_api_error_from_stream(self) -> None:
        connection = Connection("local", "Docker local", "unix:///var/run/docker.sock")
        with patch.object(
            self.service,
            "_request",
            return_value=b'{"status":"Pulling"}\n{"error":"not found"}\n',
        ):
            with self.assertRaises(DockerConnectionError) as exc:
                self.service.pull_image(connection, "missing:image")
        self.assertIn("not found", str(exc.exception))

    def test_create_container_uses_name_and_start_flag(self) -> None:
        connection = Connection("local", "Docker local", "unix:///var/run/docker.sock")
        with patch.object(
            self.service,
            "_request_json",
            return_value=b'{"Id":"abc123"}',
        ) as request_json, patch.object(self.service, "start_container") as start_container:
            response = self.service.create_container(
                connection,
                "nginx:latest",
                "web",
                "sleep 10",
                start=False,
            )
        self.assertEqual(response["Id"], "abc123")
        request_json.assert_called_once()
        self.assertIn("/containers/create?name=web", request_json.call_args.args[2])
        self.assertEqual(request_json.call_args.args[3]["Cmd"], ["sleep", "10"])
        start_container.assert_not_called()

    def test_create_network_includes_flags(self) -> None:
        connection = Connection("local", "Docker local", "unix:///var/run/docker.sock")
        with patch.object(
            self.service,
            "_request_json",
            return_value=b'{"Id":"net123"}',
        ) as request_json:
            response = self.service.create_network(
                connection,
                "frontend",
                "bridge",
                internal=True,
                attachable=True,
                enable_ipv6=True,
            )
        self.assertEqual(response["Id"], "net123")
        request_json.assert_called_once()
        body = request_json.call_args.args[3]
        self.assertEqual(body["Name"], "frontend")
        self.assertEqual(body["Driver"], "bridge")
        self.assertTrue(body["Internal"])
        self.assertTrue(body["Attachable"])
        self.assertTrue(body["EnableIPv6"])

    def test_prune_images_returns_decoded_payload(self) -> None:
        connection = Connection("local", "Docker local", "unix:///var/run/docker.sock")
        with patch.object(
            self.service,
            "_request",
            return_value=b'{"ImagesDeleted":[{"Deleted":"img1"}],"SpaceReclaimed":1024}',
        ) as request:
            response = self.service.prune_images(connection)
        request.assert_called_once_with(connection, "POST", "/images/prune")
        self.assertEqual(response["SpaceReclaimed"], 1024)

    def test_prune_volumes_returns_decoded_payload(self) -> None:
        connection = Connection("local", "Docker local", "unix:///var/run/docker.sock")
        with patch.object(
            self.service,
            "_request",
            return_value=b'{"VolumesDeleted":["vol1","vol2"]}',
        ) as request:
            response = self.service.prune_volumes(connection)
        request.assert_called_once_with(connection, "POST", "/volumes/prune")
        self.assertEqual(response["VolumesDeleted"], ["vol1", "vol2"])

    def test_prune_networks_returns_decoded_payload(self) -> None:
        connection = Connection("local", "Docker local", "unix:///var/run/docker.sock")
        with patch.object(
            self.service,
            "_request",
            return_value=b'{"NetworksDeleted":["net1"]}',
        ) as request:
            response = self.service.prune_networks(connection)
        request.assert_called_once_with(connection, "POST", "/networks/prune")
        self.assertEqual(response["NetworksDeleted"], ["net1"])


if __name__ == "__main__":
    unittest.main()
