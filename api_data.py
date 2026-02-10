#!/usr/bin/env .venv/bin/python


import asyncio, httpx, json, logging, os, random, redis, time
from decimal import Decimal
from aioquic.asyncio import serve, QuicConnectionProtocol
from aioquic.h3.connection import H3Connection, H3_ALPN
from aioquic.h3.events import HeadersReceived, DataReceived
from aioquic.quic.configuration import QuicConfiguration
from dotenv import load_dotenv

# ────────────── Load env ──────────────
load_dotenv()

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
API_PORT = int(os.getenv("API_PORT"))
USER_AGENTS = [ua.strip() for ua in os.getenv("USER_AGENTS", "Poller/1.0").split(",")]
REQUEST_FROMS = [r.strip() for r in os.getenv("REQUEST_FROMS", "req1,req2").split(",")]

logging.basicConfig(level=(logging.DEBUG if LOG_LEVEL == "DEBUG" else logging.INFO))
logger = logging.getLogger("quic_redis_poller")

# ────────────── Redis ──────────────
r = redis.Redis(
    host=REDIS_HOST, 
    port=REDIS_PORT, 
    decode_responses=True)

try:
    r.ping()
    logger.info("✅ Connected to Redis")
except redis.exceptions.ConnectionError as e:
    logger.error("❌ Redis connection failed: %s", e)
    exit(1)

# ────────────── In-memory stores ──────────────
last_min10s = {}             # requestFrom -> float
latest_data = {}             # {"game": {provider: data}}
webtransport_sessions = {}   # sid -> {"protocol": QuicConnectionProtocol, "send_datagram": fn}
current_game = None          # {"name":..., "provider":...}

# ────────────── Utility functions ──────────────
async def broadcast(data):
    message = json.dumps(data)
    for sid, sess in list(webtransport_sessions.items()):
        send_datagram = sess.get("send_datagram")
        if send_datagram:
            try:
                send_datagram(message.encode("utf-8"))
            except Exception as e:
                logger.warning("Datagram send fail %s: %s", sid, e)
                webtransport_sessions.pop(sid, None)

# ────────────── Poller ──────────────
async def poll_single(client, game_name, provider, requestFrom):
    url_base = r.get("url")
    if not url_base:
        logger.warning("❌ No API URL set in Redis. Skipping poll.")
        return

    url = f"{url_base}/api/games"
    headers = {"Accept": "application/json", "User-Agent": random.choice(USER_AGENTS)}
    params = {"name": game_name, "manuf": provider, "requestFrom": requestFrom}

    try:
        resp = await client.get(url, headers=headers, params=params)
        resp.raise_for_status()
        data_list = resp.json().get("data", [])
        if not data_list:
            logger.warning("⚠️ No data returned for %s | %s | %s", game_name, provider, requestFrom)
            return

        first = data_list[0]
        min10 = first.get("min10", 0.0)
        delta = min10 - last_min10s.get(requestFrom, 0.0)
        last_min10s[requestFrom] = min10

        # Only broadcast if new data
        last_entry = latest_data.get(provider)
        if last_entry and last_entry.get("min10") == min10:
            return

        now_time = Decimal(str(time.time()))
        new_data = {**first, "last_updated": str(now_time), "delta": delta}
        latest_data[provider] = new_data

        # Write to Redis
        redis_key = f"api_data:{game_name}:{provider}"
        r.set(redis_key, json.dumps(new_data))

        # Broadcast immediately
        await broadcast(new_data)
        logger.info("⚡ [%s | %s] min10=%.2f Δ=%.2f", game_name, requestFrom, min10, delta)

    except httpx.ConnectError:
        logger.warning("❌ Cannot reach API %s. Will retry next poll.", url)
    except Exception as e:
        logger.exception("Poll failed for %s [%s]: %s", game_name, requestFrom, e)

async def poller_loop():
    global current_game
    timeout = httpx.Timeout(5.0, connect=2.0, read=5.0, write=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        while True:
            try:
                # Read single game from Redis
                game_json = r.get("game")
                if not game_json:
                    logger.warning("❌ No game set in Redis under 'game'. Waiting...")
                    await asyncio.sleep(2)
                    continue

                game_data = json.loads(game_json)
                name, provider = game_data.get("name"), game_data.get("provider")
                if not name or not provider:
                    logger.warning("❌ Invalid game JSON: %s", game_json)
                    await asyncio.sleep(2)
                    continue

                # Restart poll if game changed
                if current_game != (name, provider):
                    logger.info("🔔 Switching to new game: %s | %s", name, provider)
                    current_game = (name, provider)
                    latest_data.clear()
                    last_min10s.clear()

                tasks = [poll_single(client, name, provider, req) for req in REQUEST_FROMS]
                await asyncio.gather(*tasks, return_exceptions=True)

            except Exception as e:
                logger.warning("Error polling game: %s", e)

            await asyncio.sleep(0.2)

# ────────────── QUIC/WebTransport ──────────────
class WebTransportProtocol(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._h3 = H3Connection(self._quic, enable_webtransport=True)
        self._session_id = None

    def quic_event_received(self, event):
        for h3_event in self._h3.handle_event(event):
            if isinstance(h3_event, HeadersReceived):
                stream_id = h3_event.stream_id
                self._session_id = stream_id
                webtransport_sessions[stream_id] = {
                    "protocol": self,
                    "send_datagram": lambda data: self._quic.send_datagram_frame(data)
                }
                self.transmit()

                # Send latest snapshot immediately
                for provider, data in latest_data.items():
                    self._quic.send_datagram_frame(json.dumps(data).encode("utf-8"))

            elif isinstance(h3_event, DataReceived):
                # Echo received data
                self._quic.send_stream_data(h3_event.stream_id, b"Echo: " + h3_event.data, end_stream=True)
                self.transmit()

async def quic_server():
    config = QuicConfiguration(is_client=False, alpn_protocols=H3_ALPN)
    config.load_cert_chain("cert.pem", "key.pem")
    server = await serve(
        host="::",
        port=API_PORT,
        configuration=config,
        create_protocol=WebTransportProtocol
    )
    logger.info("🔐 QUIC/WebTransport server running on UDP :%s", API_PORT)
    try:
        await asyncio.Future()  # run forever
    finally:
        server.close()
        await server.wait_closed()

# ────────────── Entrypoint ──────────────
async def main():
    logger.info("🚀 Starting real-time poller + QUIC server...")
    await asyncio.gather(
        poller_loop(),
        quic_server()
    )

if __name__ == "__main__":
    asyncio.run(main())
    