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
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")
RTP_PORT = int(os.getenv("RTP_PORT"))
USER_AGENTS = [ua.strip() for ua in os.getenv("USER_AGENTS", "Poller/1.0").split(",")]
REQUEST_FROMS = [r.strip() for r in os.getenv("REQUEST_FROMS", "req1,req2").split(",")]
URLS_LIST = [url.strip() for url in os.getenv("URLS").split(",") if os.getenv("URLS").strip()]
URLS = {url: url for url in URLS_LIST}
URL_BASE = next((url for url in URLS if 'lll' in url), None)    
ENDPOINTS_LIST = [ep.strip() for ep in os.getenv("ENDPOINTS").split(",") if os.getenv("ENDPOINTS").strip()]
ENDPOINTS = {ep: ep for ep in ENDPOINTS_LIST}
ENDPOINT = next((ep for ep in ENDPOINTS if 'yRt' in ep), None)    

logging.basicConfig(level=(logging.DEBUG if LOG_LEVEL == "DEBUG" else logging.INFO))
logger = logging.getLogger("quic_redis_poller")

# ────────────── Redis ──────────────
r = redis.Redis(
    host=REDIS_HOST, 
    port=REDIS_PORT, 
    password=REDIS_PASSWORD,
    decode_responses=True)

try:
    r.ping()
    logger.info("✅ Connected to Redis")
except redis.exceptions.ConnectionError as e:
    logger.error("❌ Redis connection failed: %s", e)
    raise SystemExit(1)

# ────────────── In-memory stores ──────────────
# last_max = {}             # requestFrom -> float
latest_data = {}             # {"game": {provider: data}}
webtransport_sessions = {}   # sid -> {"protocol": QuicConnectionProtocol, "send_datagram": fn}
# current_game = None          # {"name":..., "provider":...}

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
async def poll_single(client):
    if not URL_BASE:
        logger.warning("❌ No API URL set in Redis. Skipping poll.")
        return

    url = f"{URL_BASE}{ENDPOINT}"
    headers = {"Accept": "application/json", "User-Agent": random.choice(USER_AGENTS)}

    try:
        resp = await client.post(url, headers=headers, json={})
        resp.raise_for_status()

        data_list = resp.json().get("communityRtp", {}).get("topGamesRtp", [])

        if not data_list:
            logger.warning("⚠️ No RTP data returned for RTP")
            return

        # Only broadcast if new data
        new_hash = json.dumps(data_list, sort_keys=True)

        if latest_data.get("_hash") == new_hash:
            logger.warning("No RTP changes")
            return
        
        now_time = Decimal(str(time.time()))
        first = data_list[0]
        new_data = {**first, "last_updated": str(now_time)}

        latest_data["_hash"] = new_hash
        latest_data["rtp"] = data_list

        r.set("rtp_data", json.dumps(latest_data, sort_keys=True))

        # Broadcast immediately
        await broadcast(new_data)
        logger.info(f"{latest_data}")
        # logger.info("⚡ [%s | %s] min10=%.2f Δ=%.2f", game_name, requestFrom, min10, delta)
        # logger.info(
        #     "⚡ gameId=%s min=%s max=%s betAmount=%s trend=%s",
        #     first.get("gameId"),
        #     first.get("min"),
        #     first.get("max"),
        #     first.get("betAmount"),
        #     first.get("trend")
        # )
    except httpx.ConnectError:
        logger.warning("❌ Cannot reach API %s. Will retry next poll.", url)
    except Exception as e:
        logger.exception("Poll failed: %s", e)

async def poller_loop():
    timeout = httpx.Timeout(5.0, connect=2.0, read=5.0, write=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        while True:
            try:
                await poll_single(client)

            except Exception:
                logger.exception("Poll loop error")

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
                for data in latest_data.items():
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
        port=RTP_PORT,
        configuration=config,
        create_protocol=WebTransportProtocol
    )

    logger.info("🔐 QUIC/WebTransport server running on UDP :%s", RTP_PORT)
    
    try:
        await asyncio.Future()  # run forever
    finally:
        server.close()
        await server.wait_closed()
        
        try:
            r.delete("rtp_data")
            r.close()
        except Exception:
            pass

# ────────────── Entrypoint ──────────────
async def main():
    logger.info("🚀 Starting real-time poller + QUIC server...")
    await asyncio.gather(
        poller_loop(),
        quic_server()
    )
    

if __name__ == "__main__":
    asyncio.run(main())
    