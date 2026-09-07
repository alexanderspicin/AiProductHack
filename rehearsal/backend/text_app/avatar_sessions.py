"""Bounded avatar reservations. Creating a training never starts billable media."""
import asyncio
from collections import deque
from dataclasses import dataclass, field
import time
from uuid import uuid4

import httpx

from .avatar_profiles import PROFILES
from .budget import local_setting
from .store import Conflict


@dataclass
class Lease:
    request_id: str
    profile: str
    token: str = field(default_factory=lambda: str(uuid4()), repr=False)
    public: dict = field(default_factory=dict, repr=False)
    conversation_id: str = ""
    deadline: float = 0
    connected: bool = False
    timer: asyncio.Task | None = None


class AvatarSessions:
    def __init__(self, *, client=None):
        self.client = client
        self.leases: dict[str, Lease] = {}
        self.lock = asyncio.Lock()
        self.seen = deque(maxlen=1000)
        self.pal_id = local_setting("TAVUS_PAL_ID")
        # Free Anam limits a call to 3 minutes. Explicitly raise only after plan review.
        self.max_seconds = min(180, max(30, int(local_setting("AVATAR_SESSION_SECONDS", "180"))))

    async def request(self, method, url, *, headers, json=None):
        async def send(client):
            response = await client.request(method, url, headers=headers, json=json, timeout=15, follow_redirects=False)
            if not response.is_success:
                raise Conflict(f"Видеосервис отклонил запрос (HTTP {response.status_code}). Повторов нет; можно продолжить без видео.")
            return response.json() if response.content else {}
        if self.client:
            return await send(self.client)
        async with httpx.AsyncClient() as client:
            return await send(client)

    async def prepare(self, sid, profile, request_id, *, audio_only=False):
        async with self.lock:
            current = self.leases.get(sid)
            if current:
                if current.request_id == request_id and current.profile == profile and (current.public.get('provider') == 'audio') == audio_only:
                    return current.public.copy()
                raise Conflict("Разговор уже подключается или ещё останавливается.")
            if (sid, request_id) in self.seen:
                raise Conflict("Эта попытка подключения уже закончена. Начните новую явно.")
            if self.leases:
                raise Conflict("На этом локальном стенде доступен один живой разговор. Сначала отключите предыдущий.")
            lease = Lease(request_id=request_id, profile=profile)
            self.leases[sid] = lease
            self.seen.append((sid, request_id))
            provider = "audio" if audio_only else PROFILES[profile]["provider"]
            lease.public = {"provider": provider, "profile": profile, "lease": lease.token,
                            "max_seconds": self.max_seconds, "path": f"/api/text/sessions/{sid}/voice/ws?lease={lease.token}"}
            try:
                if provider == "tavus":
                    headers = {"x-api-key": local_setting("TAVUS_API_KEY")}
                    if not self.pal_id:
                        pal = await self.request("POST", "https://tavusapi.com/v2/pals", headers=headers,
                            json={"pal_name": "Rehearsal training audio", "pipeline_mode": "echo",
                                  "default_face_id": PROFILES[profile]["face_id"]})
                        self.pal_id = pal["pal_id"]
                    result = await self.request("POST", "https://tavusapi.com/v2/conversations", headers=headers,
                        json={"pal_id": self.pal_id, "face_id": PROFILES[profile]["face_id"],
                              "conversation_name": "Rehearsal training", "properties": {
                                  "max_call_duration": self.max_seconds, "participant_left_timeout": 0,
                                  "participant_absent_timeout": 25}})
                    lease.conversation_id = result["conversation_id"]
                    lease.public.update(conversation_id=lease.conversation_id, conversation_url=result["conversation_url"])
                elif provider == "anam":
                    result = await self.request("POST", "https://api.anam.ai/v1/auth/session-token",
                        headers={"Authorization": "Bearer " + local_setting("ANAM_API_KEY")}, json={
                            "personaConfig": {"avatarId": PROFILES[profile]["face_id"], "avatarModel": "cara-4",
                                "enableAudioPassthrough": True, "maxSessionLengthSeconds": self.max_seconds},
                            "sessionOptions": {"enableSessionReplay": False, "videoQuality": "high", "showAiAvatarDisclosure": True}})
                    lease.public["session_token"] = result["sessionToken"]
                lease.deadline = time.monotonic() + 40
                lease.timer = asyncio.create_task(self._expire(sid, lease))
                return lease.public.copy()
            except BaseException:
                # If the provider returned an ID, close it even if local preparation failed.
                if lease.conversation_id:
                    try:
                        await self._end_tavus(lease)
                    except Exception:
                        lease.deadline = time.monotonic()
                        raise Conflict("Не удалось подтвердить закрытие видео. Повторите отключение перед новым запуском.") from None
                self.leases.pop(sid, None)
                raise

    async def _expire(self, sid, lease):
        await asyncio.sleep(40)
        if self.leases.get(sid) is lease and not lease.connected:
            try:
                await self.stop(sid)
            except Exception:
                # Retain failed lease and block new calls until explicit stop succeeds.
                pass

    def claim(self, sid, token):
        lease = self.leases.get(sid)
        if not lease or lease.token != token or lease.connected or time.monotonic() > lease.deadline:
            raise Conflict("Подключение истекло или уже используется.")
        lease.connected = True
        if lease.timer:
            lease.timer.cancel()
        return lease

    async def _end_tavus(self, lease):
        await self.request("POST", f"https://tavusapi.com/v2/conversations/{lease.conversation_id}/end",
                           headers={"x-api-key": local_setting("TAVUS_API_KEY")})
        lease.conversation_id = ""

    async def stop(self, sid, request_id=None):
        async with self.lock:
            lease = self.leases.get(sid)
            if request_id and (sid, request_id) not in self.seen:
                self.seen.append((sid, request_id))
            if lease and request_id and lease.request_id != request_id:
                return
            if not lease:
                return
            if lease.timer and lease.timer is not asyncio.current_task():
                lease.timer.cancel()
            if lease.conversation_id:
                await self._end_tavus(lease)
            # Anam SDK closes its data/signalling channel. The server-side max duration
            # additionally bounds usage if the tab crashes before stopStreaming().
            self.leases.pop(sid, None)

    async def close(self):
        for sid in list(self.leases):
            await self.stop(sid)
