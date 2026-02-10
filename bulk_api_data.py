#!/usr/bin/env .venv/bin/python


import asyncio, httpx, json, logging, os, random, redis, time
from decimal import Decimal
from aioquic.asyncio import serve, QuicConnectionProtocol
from aioquic.h3.connection import H3Connection, H3_ALPN
from aioquic.h3.events import HeadersReceived, DataReceived
from aioquic.quic.configuration import QuicConfiguration
from database import db
from dotenv import load_dotenv

# ────────────── Load env ──────────────
load_dotenv()

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
BULK_API_PORT = int(os.getenv("BULK_API_PORT"))
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

def redis_merge(redis_key: str, path: list, value: dict):
    """
    Merge a value into a nested JSON structure in Redis.
    path = list of keys to traverse/create
    """
    raw = r.get(redis_key)
    data = json.loads(raw) if raw else {}
    
    node = data
    for key in path[:-1]:
        if key not in node:
            node[key] = {}
        node = node[key]
    node[path[-1]] = value

    r.set(redis_key, json.dumps(data))

# ────────────── In-memory stores ──────────────
last_min10s = {}             # requestFrom -> float
latest_data = {}             # {"game": {provider: data}}
webtransport_sessions = {}   # sid -> {"protocol": QuicConnectionProtocol, "send_datagram": fn}

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
async def poll_bulk(client, provider, requestFrom, game_name: str | None = None):
    url_base = r.get("trend_url")
    if not url_base:
        logger.warning("❌ No API URL set in Redis. Skipping poll.")
        return

    url = f"{url_base}/api/games"
    headers = {"Accept": "application/json", "User-Agent": random.choice(USER_AGENTS)}
    params = {"manuf": provider, "requestFrom": requestFrom}

    if game_name:
        params["name"] = game_name  # single game

    try:
        resp = await client.get(url, headers=headers, params=params)
        resp.raise_for_status()
        data_list = resp.json().get("data", [])
        if not data_list:
            if game_name:
                logger.warning("⚠️ No data returned for single game=%s | provider=%s | requestFrom=%s", game_name, provider, requestFrom)
            else:
                logger.warning("⚠️ No data returned for provider=%s | requestFrom=%s", provider, requestFrom)
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

        # Merge all games into Redis (bulk or single)
        for data in data_list:
            # if data.get("value") < 90 or data.get("name") == "Wild Ape#3258": continue
            if data.get("name") == "Wild Ape#3258": continue
            
            g_name = data.get("name") if not game_name else game_name
            key_path = [ provider, g_name, requestFrom ]
            
            redis_merge("trend_data", key_path, data)
            # Broadcast each game immediately
            await broadcast(data)

        # Write to Redis
        # redis_key = f"trend_data:{game_name}:{provider}"
        # r.set(redis_key, json.dumps(new_data))
    
        # Process and store/broadcast your data here
        # for data in data_list[0]:
        #     print(data)
            # Add timestamp, delta, etc. as needed
            # redis_key = f"trend_data:{game_name}:{provider}"
            # redis_key = f"{game_name or 'bulk'}:{provider}:{requestFrom}"
            # r.set(redis_key, json.dumps(data))
            # # Optionally broadcast immediately
            # await broadcast(game_name or "bulk", provider, data)
            
        # # Broadcast immediately
        # await broadcast(new_data)
        # logger.info("⚡ [%s | %s] min10=%.2f Δ=%.2f", game_name, requestFrom, min10, delta)

    except httpx.ConnectError:
        logger.warning("❌ Cannot reach API %s. Will retry next poll.", url)
    except Exception as e:
        logger.exception("Poll failed for %s [%s]: %s", provider, requestFrom, e)

async def poller_loop():
    timeout = httpx.Timeout(5.0, connect=2.0, read=5.0, write=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        while True:
            try:
                games_json = r.get("filtered_games")
                if not games_json:
                    logger.warning("❌ No game set in Redis under 'game'. Waiting...")
                    await asyncio.sleep(2)
                    continue
                
                games = json.loads(games_json)
                game_names = [ g["name"] for g in games ]
                
                provider_raw = r.get("trend_provider")
                provider_json = json.loads(provider_raw)
                provider = provider_json.get("initial")
                
                if not game_names or not provider:
                    logger.warning("❌ Invalid game JSON: %s", games)
                    await asyncio.sleep(2)
                    continue
                
                tasks = []
                # Bulk game polling
                tasks.extend([poll_bulk(client, provider, req) for req in REQUEST_FROMS])
                # Single game polling                                    
                all_games = list(
                    db["GAME"].find(
                        {"provider": provider},
                        {"_id": 0, "name": 1}
                    )
                )
                
                search_games = [ g["name"] for g in all_games if g["name"] in game_names ]
                
                for game_name in search_games:
                    tasks.extend([poll_bulk(client, provider, req, game_name) for req in REQUEST_FROMS])
                
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
        port=BULK_API_PORT,
        configuration=config,
        create_protocol=WebTransportProtocol
    )
    logger.info("🔐 QUIC/WebTransport server running on UDP :%s", BULK_API_PORT)
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
    