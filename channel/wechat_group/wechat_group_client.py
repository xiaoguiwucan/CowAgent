"""Subprocess client for the Node.js Wechaty sidecar."""

import json
import os
import subprocess
import threading
from typing import Callable, Iterable, Optional

from channel.wechat_group.protocol import (
    SidecarCommand,
    SidecarCommandType,
    build_send_text_command,
    parse_sidecar_event,
)
from common.log import logger
from config import conf


class WechatGroupClient:
    def __init__(self, event_handler: Optional[Callable] = None):
        self.event_handler = event_handler
        self.process = None
        self._reader_thread = None
        self._lock = threading.Lock()

    def start(self):
        if self.process and self.process.poll() is None:
            return
        command = self._build_command()
        logger.info("[wechat_group] starting sidecar: {}".format(" ".join(command)))
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            cwd=self._sidecar_dir(),
        )
        self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._reader_thread.start()
        self._stderr_thread = threading.Thread(target=self._read_stderr_loop, daemon=True)
        self._stderr_thread.start()

    def stop(self):
        try:
            self.send_command(SidecarCommand(SidecarCommandType.STOP))
        except Exception:
            pass
        if self.process and self.process.poll() is None:
            self.process.terminate()

    def list_rooms(self):
        self.send_command(SidecarCommand(SidecarCommandType.LIST_ROOMS))

    def relogin(self):
        self.send_command(SidecarCommand(SidecarCommandType.RELOGIN))

    def send_text(self, room_id: str, text: str, mention_ids=None):
        cooldown_minutes = conf().get("wechat_group_alias_sync_cooldown_minutes", 1)
        self.send_command(build_send_text_command(room_id, text, mention_ids, int(cooldown_minutes or 1)))

    def send_file(self, room_id: str, path: str):
        self.send_command(SidecarCommand(SidecarCommandType.SEND_FILE, {
            "room_id": room_id,
            "path": path,
        }))

    def send_image(self, room_id: str, path: str):
        self.send_command(SidecarCommand(SidecarCommandType.SEND_IMAGE, {
            "room_id": room_id,
            "path": path,
        }))

    def send_audio(self, room_id: str, path: str):
        self.send_command(SidecarCommand(SidecarCommandType.SEND_AUDIO, {
            "room_id": room_id,
            "path": path,
        }))

    def send_command(self, command: SidecarCommand):
        if not self.process or not self.process.stdin:
            raise RuntimeError("wechat group sidecar is not started")
        line = json.dumps(command.to_json(), ensure_ascii=False)
        with self._lock:
            self.process.stdin.write(line + "\n")
            self.process.stdin.flush()

    def _read_loop(self):
        if not self.process or not self.process.stdout:
            return
        for line in self.process.stdout:
            try:
                event = parse_sidecar_event(json.loads(line))
                if self.event_handler:
                    self.event_handler(event)
            except Exception as e:
                logger.warning("[wechat_group] failed to parse sidecar line: {}, line={}".format(e, line[:200]))

    def _read_stderr_loop(self):
        if not self.process or not self.process.stderr:
            return
        for line in self.process.stderr:
            line = line.strip()
            if line:
                logger.warning("[wechat_group] sidecar stderr: {}".format(line))

    def _build_command(self) -> Iterable[str]:
        node = conf().get("wechat_group_sidecar_node") or "node"
        return [node, "wechaty-sidecar.mjs", self._build_sidecar_config_arg()]

    def _build_sidecar_config_arg(self) -> str:
        data_dir = conf().get("wechat_group_sidecar_memory_path") or os.path.join(
            os.path.expanduser("~"),
            ".cow",
            "wechat_group",
        )
        media_dir = conf().get("wechat_group_media_dir") or os.path.join(data_dir, "media")
        config = {
            "puppet": conf().get("wechat_group_puppet") or "wechaty-puppet-wechat4u",
            "memory_path": data_dir,
            "media_dir": media_dir,
            "room_ids": conf().get("wechat_group_room_ids", []),
            "room_names": conf().get("wechat_group_names", []),
            "alias_sync_cooldown_minutes": conf().get("wechat_group_alias_sync_cooldown_minutes", 1),
        }
        return json.dumps(config, ensure_ascii=False)

    @staticmethod
    def _sidecar_dir() -> str:
        return os.path.join(os.path.dirname(__file__), "sidecar")
